//! E1 Biscuit bench binary.
//!
//! Two modes:
//!   * `bench   <fixtures_dir> <out_csv>` — measure exercise-time authorize
//!     latency (p50/p95/p99), single-core throughput, and token size vs depth
//!     over the allow-stream of every fixture. Emits CSV in the shared schema.
//!   * `verify  <fixtures_dir> <out_json>` — emit ALLOW/DENY verdicts for a
//!     fixed subset (first 50 allow + all crafted violations) of every fixture,
//!     for the cross-system correctness gate (`python/verify_gate.py`).
//!
//! Every CSV row carries platform metadata (host, os, arch, cpu, runtime,
//! sandbox flag). This sandbox is aarch64 Linux and produces INDICATIVE shape
//! numbers only; the official numbers come from the owner's Apple-silicon Mac
//! mini (see README).

use biscuit_auth::{KeyPair, PublicKey};
use e1_biscuit::{authorize_once, build_token_bytes, epoch_of, Fixture};
use std::io::Write;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

// --- shared platform stamp / time helpers -----------------------------------

fn env_or(k: &str, d: &str) -> String {
    std::env::var(k).unwrap_or_else(|_| d.to_string())
}

fn now_rfc3339() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs() as i64;
    epoch_to_rfc3339(secs)
}

fn epoch_to_rfc3339(secs: i64) -> String {
    let z = secs.div_euclid(86400) + 719468;
    let rem = secs.rem_euclid(86400);
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let yr = if m <= 2 { y + 1 } else { y };
    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}Z",
        yr,
        m,
        d,
        rem / 3600,
        (rem % 3600) / 60,
        rem % 60
    )
}

const CSV_HEADER: &str = "schema,ts_utc,host,os,arch,cpu,runtime,sandbox,system,config,depth,fanout,n_exercises,p50_ns,p95_ns,p99_ns,mean_ns,throughput_ops_s,token_bytes";

struct Plat {
    ts: String,
    host: String,
    os: String,
    arch: String,
    cpu: String,
    runtime: String,
    sandbox: String,
}

fn platform() -> Plat {
    Plat {
        ts: now_rfc3339(),
        host: env_or("PCT_HOST", &env_or("HOSTNAME", "unknown")),
        os: std::env::consts::OS.to_string(),
        arch: std::env::consts::ARCH.to_string(),
        cpu: env_or("PCT_CPU", "unknown"),
        runtime: env_or("PCT_RUNTIME", "rustc-1.96.1"),
        sandbox: env_or("PCT_SANDBOX", "true"),
    }
}

fn pct(sorted: &[u128], p: f64) -> u128 {
    if sorted.is_empty() {
        return 0;
    }
    let idx = ((p / 100.0) * (sorted.len() as f64 - 1.0)).round() as usize;
    sorted[idx.min(sorted.len() - 1)]
}

fn list_fixtures(dir: &str) -> Vec<String> {
    let mut v: Vec<String> = std::fs::read_dir(dir)
        .expect("read fixtures dir")
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| {
            p.file_name()
                .and_then(|n| n.to_str())
                .map(|n| n.starts_with("graph_") && n.ends_with(".json"))
                .unwrap_or(false)
        })
        .map(|p| p.to_string_lossy().to_string())
        .collect();
    v.sort();
    v
}

fn load(path: &str) -> Fixture {
    let s = std::fs::read_to_string(path).expect("read fixture");
    serde_json::from_str(&s).expect("parse fixture")
}

/// Build tokens for every chain in a fixture, returning (root_public, Vec<bytes>).
fn build_all(fx: &Fixture) -> (PublicKey, Vec<Vec<u8>>) {
    // One root key for the whole config (the "operator"); deterministic content
    // sizes do not depend on the key material.
    let root = KeyPair::new();
    let pubk = root.public();
    let tokens: Vec<Vec<u8>> = fx
        .chains
        .iter()
        .map(|c| build_token_bytes(&c.hops, &fx.jurisdiction, &root))
        .collect();
    (pubk, tokens)
}

fn run_bench(dir: &str, out_csv: &str) {
    let p = platform();
    let mut out = String::new();
    out.push_str(CSV_HEADER);
    out.push('\n');

    for path in list_fixtures(dir) {
        let fx = load(&path);
        let (pubk, tokens) = build_all(&fx);
        let token_bytes = tokens[0].len();

        // Allow-stream only for timing (happy authorize path).
        // PCT_MAX_PER_CONFIG caps the timed stream so the repeated-execution
        // variability sweep (scripts/repeat_e1.sh) stays affordable; unset or
        // 0 means "every allow exercise in the fixture", i.e. the official run.
        let mut allow: Vec<_> = fx
            .exercises
            .iter()
            .filter(|e| e.expect == "allow")
            .collect();
        let cap: usize = env_or("PCT_MAX_PER_CONFIG", "0").parse().unwrap_or(0);
        if cap > 0 && allow.len() > cap {
            allow.truncate(cap);
        }

        // Warmup.
        for e in allow.iter().take(200) {
            let t = &tokens[e.chain_index as usize % tokens.len()];
            let _ = authorize_once(
                t,
                pubk,
                e.amount_micro,
                &e.resource_url,
                epoch_of(&e.at),
                &e.jurisdiction,
            );
        }

        // Timed loop.
        let mut nanos: Vec<u128> = Vec::with_capacity(allow.len());
        let mut allow_failures = 0u64;
        for e in &allow {
            let t = &tokens[e.chain_index as usize % tokens.len()];
            let at = epoch_of(&e.at);
            let start = Instant::now();
            let ok = authorize_once(t, pubk, e.amount_micro, &e.resource_url, at, &e.jurisdiction);
            nanos.push(start.elapsed().as_nanos());
            if !ok {
                allow_failures += 1;
            }
        }
        if allow_failures > 0 {
            eprintln!(
                "WARNING: {} allow exercises failed authorize in {} (correctness bug!)",
                allow_failures, path
            );
        }
        nanos.sort_unstable();
        let n = nanos.len();
        let sum: u128 = nanos.iter().sum();
        let mean = if n > 0 { sum / n as u128 } else { 0 };
        let total_s = sum as f64 / 1e9;
        let thr = if total_s > 0.0 { n as f64 / total_s } else { 0.0 };

        out.push_str(&format!(
            "pct-eval/e1@1,{},{},{},{},{},{},{},biscuit,na,{},{},{},{},{},{},{},{:.1},{}\n",
            p.ts,
            p.host,
            p.os,
            p.arch,
            p.cpu,
            p.runtime,
            p.sandbox,
            fx.depth,
            fx.fanout,
            n,
            pct(&nanos, 50.0),
            pct(&nanos, 95.0),
            pct(&nanos, 99.0),
            mean,
            thr,
            token_bytes,
        ));
        println!(
            "biscuit d={} f={} n={} p50={}ns p99={}ns token={}B",
            fx.depth,
            fx.fanout,
            n,
            pct(&nanos, 50.0),
            pct(&nanos, 99.0),
            token_bytes
        );
    }

    if let Some(parent) = std::path::Path::new(out_csv).parent() {
        std::fs::create_dir_all(parent).ok();
    }
    let mut f = std::fs::File::create(out_csv).expect("create csv");
    f.write_all(out.as_bytes()).expect("write csv");
    println!("wrote {}", out_csv);
}

/// Fixed cross-system gate subset: first 50 allow ids + every violation id.
fn gate_ids(fx: &Fixture) -> Vec<&e1_biscuit::Exercise> {
    let mut v: Vec<&e1_biscuit::Exercise> = Vec::new();
    let mut allow_taken = 0;
    for e in &fx.exercises {
        if e.expect == "allow" {
            if allow_taken < 50 {
                v.push(e);
                allow_taken += 1;
            }
        } else {
            v.push(e);
        }
    }
    v
}

fn run_verify(dir: &str, out_json: &str) {
    let mut top = serde_json::Map::new();
    for path in list_fixtures(dir) {
        let fx = load(&path);
        let (pubk, tokens) = build_all(&fx);
        let mut per = serde_json::Map::new();
        for e in gate_ids(&fx) {
            let t = &tokens[e.chain_index as usize % tokens.len()];
            let ok = authorize_once(
                t,
                pubk,
                e.amount_micro,
                &e.resource_url,
                epoch_of(&e.at),
                &e.jurisdiction,
            );
            per.insert(e.id.to_string(), serde_json::Value::Bool(ok));
        }
        let key = format!("d{}_f{}", fx.depth, fx.fanout);
        top.insert(key, serde_json::Value::Object(per));
    }
    if let Some(parent) = std::path::Path::new(out_json).parent() {
        std::fs::create_dir_all(parent).ok();
    }
    std::fs::write(
        out_json,
        serde_json::to_string_pretty(&serde_json::Value::Object(top)).unwrap(),
    )
    .expect("write verdicts");
    println!("wrote biscuit verdicts to {}", out_json);
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let mode = args.get(1).map(|s| s.as_str()).unwrap_or("bench");
    match mode {
        "bench" => {
            let dir = args.get(2).cloned().unwrap_or_else(|| "workloads".into());
            let out = args
                .get(3)
                .cloned()
                .unwrap_or_else(|| "results/e1-biscuit.csv".into());
            run_bench(&dir, &out);
        }
        "verify" => {
            let dir = args.get(2).cloned().unwrap_or_else(|| "workloads".into());
            let out = args
                .get(3)
                .cloned()
                .unwrap_or_else(|| "results/biscuit-verdicts.json".into());
            run_verify(&dir, &out);
        }
        other => {
            eprintln!("unknown mode {other:?}; use 'bench' or 'verify'");
            std::process::exit(2);
        }
    }
}
