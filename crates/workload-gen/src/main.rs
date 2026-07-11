//! Canonical seeded workload generator for E1.
//!
//! Emits delegation-graph fixtures that ALL THREE benchmarked systems consume
//! unchanged: the Biscuit bench (Rust), the capability-grant@1 bench (Python),
//! and the OPA/Rego baseline. The fixture is deliberately *system-neutral*: it
//! carries only the semantic caveat content per hop plus an exercise stream of
//! `(resource_url, amount, time, jurisdiction)` tuples with expected verdicts.
//! Each system's harness then materialises its own concrete token/grant/input
//! document from this one fixture, so semantic equivalence is enforced by
//! construction (plan §1 E1, integrity rule: synthetic workloads OK & declared).
//!
//! Determinism: a hand-rolled SplitMix64 PRNG seeded from the manifest seed, so
//! fixtures are byte-reproducible with no external RNG dependency. Fixtures are
//! committed to `workloads/` per the reproducibility spec.
//!
//! ## Canonical caveat semantics (identical across Biscuit / grant@1 / Rego)
//!
//! Per hop, all conjunctive and monotone-narrowing (child ⊆ parent), matching
//! exactly the `capability-grant@1` fragment in
//! `presidio_x402.capability` (the artifact under test):
//!
//! * `max_per_call_micro`  — per-call cap, micro-USD i64. child ≤ parent.
//! * `daily_limit_micro`   — rolling aggregate cap, micro-USD i64. child ≤ parent.
//! * `window_seconds`      — rolling budget window. child ≥ parent.
//! * `valid_from`/`valid_until` — RFC3339 UTC validity window. from ≥, until ≤.
//! * `endpoint_prefixes`   — http(s) URL prefixes; child extends parent on a
//!                           path/host boundary.
//!
//! Amounts are integer **micro-USD** everywhere (1_000_000 = $1.00). This keeps
//! the whole pipeline float-free (grant@1's strict canonical profile rejects
//! floats; Biscuit datalog is i64; Rego does integer comparison) — no unit or
//! rounding divergence can creep in between the systems.
//!
//! `jurisdiction` is a per-graph constant J. It is checked by Biscuit and Rego
//! (they can express equality caveats) but NOT by grant@1, whose `@1` fragment
//! deliberately omits jurisdiction (see design doc "Out of scope for @1"). It is
//! therefore held CONSTANT across every hop and every exercise so it can never
//! flip a verdict — the one documented cross-system divergence (README §
//! "Semantic equivalence").

use std::collections::BTreeMap;
use std::io::Write as _;

// ---------------------------------------------------------------------------
// Deterministic PRNG (SplitMix64) — no external dependency, byte-reproducible.
// ---------------------------------------------------------------------------

struct SplitMix64(u64);

impl SplitMix64 {
    fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }
    /// Uniform in [0, n).
    fn below(&mut self, n: u64) -> u64 {
        self.next_u64() % n
    }
}

// ---------------------------------------------------------------------------
// Civil-date <-> epoch (Howard Hinnant's algorithm) so timestamps are RFC3339
// strings (grant@1/Rego native) with no chrono dependency.
// ---------------------------------------------------------------------------

fn days_from_civil(y: i64, m: i64, d: i64) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = (y - era * 400) as i64;
    let doy = (153 * (if m > 2 { m - 3 } else { m + 9 }) + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146097 + doe - 719468
}

fn civil_from_days(z: i64) -> (i64, i64, i64) {
    let z = z + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    (if m <= 2 { y + 1 } else { y }, m, d)
}

fn epoch_to_rfc3339(secs: i64) -> String {
    let days = secs.div_euclid(86400);
    let rem = secs.rem_euclid(86400);
    let (y, m, d) = civil_from_days(days);
    let (hh, mm, ss) = (rem / 3600, (rem % 3600) / 60, rem % 60);
    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}Z",
        y, m, d, hh, mm, ss
    )
}

// ---------------------------------------------------------------------------
// Fixture model (serialised to JSON). Kept intentionally simple/flat.
// ---------------------------------------------------------------------------

use serde::Serialize;

#[derive(Serialize, Clone)]
struct HopCaveats {
    max_per_call_micro: i64,
    daily_limit_micro: i64,
    window_seconds: i64,
    valid_from: String,
    valid_until: String,
    endpoint_prefixes: Vec<String>,
}

#[derive(Serialize)]
struct Chain {
    /// Leaf index within this config (0..fanout).
    chain_index: u32,
    /// Root-first list of per-hop caveats (len == depth).
    hops: Vec<HopCaveats>,
}

#[derive(Serialize)]
struct Exercise {
    id: u64,
    chain_index: u32,
    resource_url: String,
    amount_micro: i64,
    at: String,
    jurisdiction: String,
    /// "allow" | "deny"
    expect: String,
    /// null | "over_budget" | "out_of_prefix" | "expired" | "attenuated_depth"
    violation: Option<String>,
}

#[derive(Serialize)]
struct Fixture {
    schema: String,
    depth: u32,
    fanout: u32,
    seed: u64,
    jurisdiction: String,
    /// Fixed "now" used as the centre of the validity windows (epoch + RFC3339).
    now_epoch: i64,
    now_rfc3339: String,
    n_allow_exercises: u64,
    n_violation_exercises: u64,
    chains: Vec<Chain>,
    /// The allow-stream (timing runs use this) followed by the crafted
    /// violation set (correctness gate uses allow+violations).
    exercises: Vec<Exercise>,
}

// ---------------------------------------------------------------------------
// Chain construction: monotone narrowing that satisfies grant@1's attenuation
// rules exactly (so delegate_grant / verify_chain accept it), and is equally
// expressible as Biscuit blocks and a Rego input document.
// ---------------------------------------------------------------------------

const HOST: &str = "https://api.foo.com";

fn build_hops(depth: u32, now: i64) -> Vec<HopCaveats> {
    // Base window: [now - 12h, now + 12h]. Narrowed each hop but stays wide
    // enough that every exercise 'at' (drawn near `now`) is inside the deepest
    // window.
    let base_from = now - 12 * 3600;
    let base_until = now + 12 * 3600;

    let mut hops = Vec::with_capacity(depth as usize);
    // Cumulative endpoint path, nested on '/' boundaries.
    let mut path = String::new(); // root prefix is HOST + "/"
    for i in 0..depth {
        // Monotone: caps non-increasing, window non-decreasing, validity
        // interval non-widening, prefixes extending.
        let max_per_call = 1_000_000 - (i as i64) * 50_000; // $1.00 .. down
        let daily = 10_000_000 - (i as i64) * 200_000;
        let window = 3600 + (i as i64) * 600; // child >= parent
        let vfrom = base_from + (i as i64) * 60; // child >= parent
        let vuntil = base_until - (i as i64) * 60; // child <= parent

        let prefix = if i == 0 {
            format!("{}/", HOST)
        } else {
            format!("{}{}", HOST, path)
        };
        hops.push(HopCaveats {
            max_per_call_micro: max_per_call,
            daily_limit_micro: daily,
            window_seconds: window,
            valid_from: epoch_to_rfc3339(vfrom),
            valid_until: epoch_to_rfc3339(vuntil),
            endpoint_prefixes: vec![prefix],
        });
        // Extend path for the NEXT hop (so hop i+1 nests under hop i).
        path.push_str(&format!("/seg{}", i + 1));
    }
    hops
}

/// The deepest (terminal) prefix — an exercise URL under it is under every hop.
fn deepest_prefix(hops: &[HopCaveats]) -> String {
    hops.last().unwrap().endpoint_prefixes[0].clone()
}

fn allow_url(hops: &[HopCaveats]) -> String {
    let p = deepest_prefix(hops);
    if p.ends_with('/') {
        format!("{}res", p)
    } else {
        format!("{}/res", p)
    }
}

/// Effective (tightest) caveats over the chain — used to place allow exercises
/// safely inside the admitted set, and to craft violations just outside it.
fn effective(hops: &[HopCaveats]) -> (i64, i64, i64) {
    let cap = hops.iter().map(|h| h.max_per_call_micro).min().unwrap();
    let vfrom = hops
        .iter()
        .map(|h| epoch_of(&h.valid_from))
        .max()
        .unwrap();
    let vuntil = hops
        .iter()
        .map(|h| epoch_of(&h.valid_until))
        .min()
        .unwrap();
    (cap, vfrom, vuntil)
}

fn epoch_of(rfc: &str) -> i64 {
    // Parse "YYYY-MM-DDTHH:MM:SSZ" (our own emitter — fixed format).
    let b = rfc.as_bytes();
    let num = |s: usize, e: usize| -> i64 { rfc[s..e].parse::<i64>().unwrap() };
    let _ = b;
    let (y, mo, d) = (num(0, 4), num(5, 7), num(8, 10));
    let (h, mi, s) = (num(11, 13), num(14, 16), num(17, 19));
    days_from_civil(y, mo, d) * 86400 + h * 3600 + mi * 60 + s
}

fn generate(depth: u32, fanout: u32, seed: u64, n_allow: u64) -> Fixture {
    // 2026-07-10T12:00:00Z — fixed evaluation instant (matches memory currentDate).
    let now = days_from_civil(2026, 7, 10) * 86400 + 12 * 3600;
    let jurisdiction = "EU".to_string();

    // Per-leaf seed so each chain is deterministic yet distinct. All leaves in
    // a config share the same narrowing schedule (identical structure); fanout
    // models an orchestrator handing N sub-agents an equivalent slice.
    let mut chains = Vec::with_capacity(fanout as usize);
    for ci in 0..fanout {
        chains.push(Chain {
            chain_index: ci,
            hops: build_hops(depth, now),
        });
    }
    let hops0 = &chains[0].hops;
    let (cap, vfrom, vuntil) = effective(hops0);
    let ok_url = allow_url(hops0);

    let mut rng = SplitMix64(seed ^ ((depth as u64) << 32) ^ ((fanout as u64) << 16));
    let mut exercises = Vec::new();
    let mut id: u64 = 0;

    // ----- allow stream (timing runs use exactly this) -----
    for _ in 0..n_allow {
        let ci = rng.below(fanout as u64) as u32;
        // amount strictly below the tightest cap; time strictly inside window.
        let amount = 1 + (rng.below((cap as u64).max(2) - 1)) as i64; // 1..cap-? < cap
        let span = (vuntil - vfrom).max(2) as u64;
        let at = vfrom + 1 + (rng.below(span - 1)) as i64;
        exercises.push(Exercise {
            id,
            chain_index: ci,
            resource_url: ok_url.clone(),
            amount_micro: amount,
            at: epoch_to_rfc3339(at),
            jurisdiction: jurisdiction.clone(),
            expect: "allow".into(),
            violation: None,
        });
        id += 1;
    }
    let n_allow_actual = exercises.len() as u64;

    // ----- crafted violation set (correctness gate). All three must DENY. -----
    // Each exercises exactly one axis just outside the admitted set. jurisdiction
    // is NOT among them (grant@1 cannot check it — see module docs).
    let mid_at = epoch_to_rfc3339((vfrom + vuntil) / 2);

    // over_budget: amount one micro-USD above the tightest per-call cap.
    exercises.push(Exercise {
        id,
        chain_index: 0,
        resource_url: ok_url.clone(),
        amount_micro: cap + 1,
        at: mid_at.clone(),
        jurisdiction: jurisdiction.clone(),
        expect: "deny".into(),
        violation: Some("over_budget".into()),
    });
    id += 1;

    // out_of_prefix: a different host entirely (fails raw starts_with AND the
    // path-boundary matcher — so Biscuit, grant@1 and Rego all deny identically).
    exercises.push(Exercise {
        id,
        chain_index: 0,
        resource_url: "https://api.evil.com/seg1/res".into(),
        amount_micro: 1,
        at: mid_at.clone(),
        jurisdiction: jurisdiction.clone(),
        expect: "deny".into(),
        violation: Some("out_of_prefix".into()),
    });
    id += 1;

    // expired: one second after the tightest valid_until.
    exercises.push(Exercise {
        id,
        chain_index: 0,
        resource_url: ok_url.clone(),
        amount_micro: 1,
        at: epoch_to_rfc3339(vuntil + 1),
        jurisdiction: jurisdiction.clone(),
        expect: "deny".into(),
        violation: Some("expired".into()),
    });
    id += 1;

    // attenuated_depth: amount within the ROOT cap but above the tightest
    // (deepest) hop cap — only present when depth > 1 (needs a narrowing hop).
    // Proves every system honours the tightest ancestor across chain depth.
    if depth > 1 {
        let root_cap = hops0[0].max_per_call_micro;
        // cap < amount <= root_cap (root_cap > cap because caps strictly narrow).
        let amount = cap + ((root_cap - cap) / 2).max(1);
        exercises.push(Exercise {
            id,
            chain_index: 0,
            resource_url: ok_url.clone(),
            amount_micro: amount,
            at: mid_at.clone(),
            jurisdiction: jurisdiction.clone(),
            expect: "deny".into(),
            violation: Some("attenuated_depth".into()),
        });
        id += 1;
    }
    let n_viol = exercises.len() as u64 - n_allow_actual;
    let _ = id;

    Fixture {
        schema: "pct-eval/e1-workload@1".into(),
        depth,
        fanout,
        seed,
        jurisdiction,
        now_epoch: now,
        now_rfc3339: epoch_to_rfc3339(now),
        n_allow_exercises: n_allow_actual,
        n_violation_exercises: n_viol,
        chains,
        exercises,
    }
}

fn main() {
    // CLI: workload-gen <out_dir> [n_allow_exercises] [seed]
    let args: Vec<String> = std::env::args().collect();
    let out_dir = args.get(1).cloned().unwrap_or_else(|| "workloads".into());
    let n_allow: u64 = args
        .get(2)
        .and_then(|s| s.parse().ok())
        .unwrap_or(3000); // sandbox default; Mac run overrides to 100_000
    let seed: u64 = args.get(3).and_then(|s| s.parse().ok()).unwrap_or(0xC0FFEE);

    std::fs::create_dir_all(&out_dir).expect("create out dir");

    let depths = [1u32, 2, 4, 6, 8, 10];
    let fanouts = [1u32, 10, 100];

    let mut manifest: BTreeMap<String, serde_json::Value> = BTreeMap::new();
    let mut configs = Vec::new();

    for &depth in &depths {
        for &fanout in &fanouts {
            let fx = generate(depth, fanout, seed, n_allow);
            let name = format!("graph_d{}_f{}.json", depth, fanout);
            let path = format!("{}/{}", out_dir, name);
            let f = std::fs::File::create(&path).expect("create fixture");
            let mut w = std::io::BufWriter::new(f);
            serde_json::to_writer(&mut w, &fx).expect("write fixture");
            w.flush().unwrap();
            configs.push(serde_json::json!({
                "file": name,
                "depth": depth,
                "fanout": fanout,
                "n_allow": fx.n_allow_exercises,
                "n_violation": fx.n_violation_exercises,
            }));
            println!(
                "wrote {} (depth={}, fanout={}, allow={}, viol={})",
                path, depth, fanout, fx.n_allow_exercises, fx.n_violation_exercises
            );
        }
    }

    manifest.insert("schema".into(), serde_json::json!("pct-eval/e1-manifest@1"));
    manifest.insert("seed".into(), serde_json::json!(seed));
    manifest.insert("n_allow_per_config".into(), serde_json::json!(n_allow));
    manifest.insert("depths".into(), serde_json::json!(depths));
    manifest.insert("fanouts".into(), serde_json::json!(fanouts));
    manifest.insert("configs".into(), serde_json::json!(configs));
    let mpath = format!("{}/manifest.json", out_dir);
    std::fs::write(
        &mpath,
        serde_json::to_string_pretty(&manifest).unwrap(),
    )
    .unwrap();
    println!("wrote {}", mpath);
}
