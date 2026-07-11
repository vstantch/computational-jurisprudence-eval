//! E3 — accumulator revocation microbenchmark (WIRED, single-core).
//!
//! Measures, on the disclosed benchmark host, the four quantities the plan names
//! for E3 against `vb_accumulator` 0.29 (Dock's universal, pairing-based
//! accumulator over BLS12-381):
//!
//!   * `non_membership_gen`    — build a non-membership witness for a non-member
//!                               against a state of `base_size` members (O(base));
//!   * `non_membership_verify` — pairing check of that witness (constant);
//!   * `epoch_root_update`      — manager recomputes the accumulator value after a
//!                               batch removal of B members (`compute_new_post_remove_batch`);
//!   * `omega_publish`          — manager publishes the public witness-update info
//!                               `Omega` for that batch (holders need it);
//!   * `witness_update`         — a holder updates its non-membership witness from
//!                               the public `Omega` after the batch removal.
//!
//! Batch sizes B ∈ {100, 1000, 10000} (`e3_accumulator::REVOCATION_BATCH_SIZES`).
//! Every timed operation is a pure function of committed, seeded inputs, so each
//! is looped for percentiles without state drift. Before timing, each result is
//! verified for correctness (witness verifies against the relevant accumulator);
//! a wrong computation is never timed. Integrity rule: measured, never estimated.
//!
//! CSV schema (one row per operation × batch):
//!   schema,ts_unix_s,host,os,arch,cpu,runtime,sandbox,library,parallel,
//!   operation,batch_size,base_size,n_iter,p50_ns,p95_ns,p99_ns,mean_ns,proof_bytes

use std::collections::HashSet;
use std::env;
use std::fs;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use ark_bls12_381::{Bls12_381, Fr, G1Affine};
use ark_ff::UniformRand;
use ark_serialize::{CanonicalSerialize, Compress};
use ark_std::rand::{rngs::StdRng, SeedableRng};

use vb_accumulator::batch_utils::Omega;
use vb_accumulator::persistence::{InitialElementsStore, State, UniversalAccumulatorState};
use vb_accumulator::positive::Accumulator; // brings `value()` into scope
use vb_accumulator::setup::{Keypair, SetupParams};
use vb_accumulator::universal::UniversalAccumulator;

use e3_accumulator::REVOCATION_BATCH_SIZES;

// ---- in-memory stores (the crate's own InMemory* are #[cfg(test)]) -----------

#[derive(Clone, Default)]
struct InitStore {
    db: HashSet<Fr>,
}
impl InitialElementsStore<Fr> for InitStore {
    fn add(&mut self, element: Fr) {
        self.db.insert(element);
    }
    fn has(&self, element: &Fr) -> bool {
        self.db.contains(element)
    }
}

#[derive(Clone, Default)]
struct MemState {
    db: HashSet<Fr>,
}
impl State<Fr> for MemState {
    fn add(&mut self, element: Fr) {
        self.db.insert(element);
    }
    fn remove(&mut self, element: &Fr) {
        self.db.remove(element);
    }
    fn has(&self, element: &Fr) -> bool {
        self.db.contains(element)
    }
    fn size(&self) -> u64 {
        self.db.len() as u64
    }
}
impl<'a> UniversalAccumulatorState<'a, Fr> for MemState {
    type ElementIterator = std::collections::hash_set::Iter<'a, Fr>;
    fn elements(&'a self) -> Self::ElementIterator {
        self.db.iter()
    }
}

// ---- helpers -----------------------------------------------------------------

fn env_or(k: &str, d: &str) -> String {
    env::var(k).unwrap_or_else(|_| d.to_string())
}

/// (p50, p95, p99, mean) in ns from per-iteration nanosecond samples.
fn stats(mut v: Vec<u128>) -> (u128, u128, u128, u128) {
    v.sort_unstable();
    let n = v.len();
    let pct = |p: f64| -> u128 {
        let idx = ((p * (n as f64 - 1.0)).round() as usize).min(n - 1);
        v[idx]
    };
    let mean = v.iter().sum::<u128>() / (n as u128);
    (pct(0.50), pct(0.95), pct(0.99), mean)
}

/// Time `f` `iters` times, returning ns samples. `f` must be side-effect free
/// w.r.t. the accumulator/state so every iteration measures the same work.
fn time_it<F: FnMut()>(iters: usize, mut f: F) -> Vec<u128> {
    // warm up (exclude first-call effects), not recorded
    for _ in 0..3.min(iters) {
        f();
    }
    let mut samples = Vec::with_capacity(iters);
    for _ in 0..iters {
        let t = Instant::now();
        f();
        samples.push(t.elapsed().as_nanos());
    }
    samples
}

fn main() {
    let out = env::args().nth(1).unwrap_or_else(|| "results/e3-accum.csv".to_string());

    // platform stamp (same env contract as the E1 harness)
    let host = env_or("PCT_HOST", &env_or("HOSTNAME", "unknown"));
    let cpu = env_or("PCT_CPU", "unknown");
    let sandbox = env_or("PCT_SANDBOX", "true");
    let runtime = env_or("PCT_RUNTIME", "rustc-1.96.1");
    let ts = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
    let os = env::consts::OS;
    let arch = env::consts::ARCH;
    const LIBRARY: &str = "vb_accumulator-0.29.0";
    const PARALLEL: &str = "false";

    // ---- setup: seeded universal accumulator with `base_size` members --------
    // max_size must exceed base_size (removable members) with headroom; the
    // universal setup also reserves max+1 non-removable initial elements.
    let base_size: usize = 20_000;
    let max_size: u64 = 30_000;
    let mut rng = StdRng::seed_from_u64(0);

    let params = SetupParams::<Bls12_381>::generate_using_rng(&mut rng);
    let keypair = Keypair::<Bls12_381>::generate_using_rng(&mut rng, &params);
    let mut initial = InitStore::default();
    let acc = UniversalAccumulator::<G1Affine>::initialize_with_all_random(
        &mut rng,
        &params,
        max_size,
        &keypair.secret_key,
        &mut initial,
    );

    // add `base_size` random members (present, and therefore removable)
    let members: Vec<Fr> = (0..base_size).map(|_| Fr::rand(&mut rng)).collect();
    let mut state = MemState::default();
    let acc = acc
        .add_batch(members.clone(), &keypair.secret_key, &initial, &mut state)
        .expect("add_batch of base members");
    assert_eq!(state.size() as usize, base_size);

    // a non-member to build / update a non-membership witness for
    let y = Fr::rand(&mut rng);
    assert!(!state.has(&y) && !initial.has(&y), "y must be a genuine non-member");

    // correctness gate: witness must verify before we time anything
    let w = acc
        .get_non_membership_witness(&y, &keypair.secret_key, &state, &params)
        .expect("non-membership witness");
    assert!(
        acc.verify_non_membership(&y, &w, &keypair.public_key, &params),
        "base non-membership witness must verify"
    );
    let proof_bytes = w.serialized_size(Compress::Yes);

    let mut rows: Vec<String> = Vec::new();
    let mut push = |op: &str, b: usize, base: usize, iters: usize, s: (u128, u128, u128, u128), pb: usize| {
        rows.push(format!(
            "e3-accum-v1,{ts},{host},{os},{arch},{cpu},{runtime},{sandbox},{LIBRARY},{PARALLEL},{op},{b},{base},{iters},{},{},{},{},{pb}",
            s.0, s.1, s.2, s.3
        ));
    };

    // ---- base ops: non-membership gen (O(base)) and verify (constant) --------
    let s = time_it(50, || {
        let _ = acc
            .get_non_membership_witness(&y, &keypair.secret_key, &state, &params)
            .unwrap();
    });
    push("non_membership_gen", 0, base_size, 50, stats(s), proof_bytes);
    eprintln!("[e3] non_membership_gen done (base={base_size})");

    let s = time_it(200, || {
        let _ = acc.verify_non_membership(&y, &w, &keypair.public_key, &params);
    });
    push("non_membership_verify", 0, base_size, 200, stats(s), proof_bytes);
    eprintln!("[e3] non_membership_verify done");

    // ---- per-batch ops -------------------------------------------------------
    for &b in REVOCATION_BATCH_SIZES.iter() {
        assert!(b <= base_size, "batch must be <= base_size");
        let removals: Vec<Fr> = members[..b].to_vec();

        // manager: new accumulator value after the batch removal (epoch root)
        let (f_v_new, v_new) = acc.compute_new_post_remove_batch(&removals, &keypair.secret_key);
        // manager: published witness-update info for the batch
        let omega = Omega::new(&[], &removals, acc.value(), &keypair.secret_key);
        // holder: update the non-membership witness from the public Omega
        let w_new = w
            .update_using_public_info_after_batch_updates(&[], &removals, &omega, &y)
            .expect("witness update after batch removal");

        // correctness gate: updated witness must verify against the NEW accumulator
        let acc_new = UniversalAccumulator::<G1Affine>::from_value(f_v_new, v_new, max_size);
        assert!(
            acc_new.verify_non_membership(&y, &w_new, &keypair.public_key, &params),
            "updated witness must verify against post-removal accumulator (B={b})"
        );

        // iteration counts scale down with B to bound wall-clock while keeping
        // enough samples for a stable p99.
        let (n_root, n_omega, n_upd) = match b {
            b if b >= 10_000 => (60usize, 30usize, 60usize),
            b if b >= 1_000 => (150, 100, 150),
            _ => (300, 200, 300),
        };

        let s = time_it(n_root, || {
            let _ = acc.compute_new_post_remove_batch(&removals, &keypair.secret_key);
        });
        push("epoch_root_update", b, base_size, n_root, stats(s), proof_bytes);

        let s = time_it(n_omega, || {
            let _ = Omega::new(&[], &removals, acc.value(), &keypair.secret_key);
        });
        push("omega_publish", b, base_size, n_omega, stats(s), proof_bytes);

        let s = time_it(n_upd, || {
            let _ = w
                .update_using_public_info_after_batch_updates(&[], &removals, &omega, &y)
                .unwrap();
        });
        push("witness_update", b, base_size, n_upd, stats(s), proof_bytes);

        eprintln!("[e3] batch B={b} done");
    }

    let header = "schema,ts_unix_s,host,os,arch,cpu,runtime,sandbox,library,parallel,operation,batch_size,base_size,n_iter,p50_ns,p95_ns,p99_ns,mean_ns,proof_bytes";
    let body = rows.join("\n");
    if let Some(dir) = std::path::Path::new(&out).parent() {
        let _ = fs::create_dir_all(dir);
    }
    fs::write(&out, format!("{header}\n{body}\n")).expect("write e3 CSV");
    println!("wrote {out} ({} rows, sandbox={sandbox}, parallel={PARALLEL})", rows.len());
}
