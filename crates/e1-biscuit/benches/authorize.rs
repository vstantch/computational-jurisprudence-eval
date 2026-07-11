//! Criterion micro-bench (methodological cross-check for the CSV binary).
//!
//! Times the exercise-time authorize path (deserialize+verify signatures, then
//! authorize) for a fixed depth-4 chain. Criterion's own statistical estimate
//! is used only to sanity-check the percentile numbers the `e1-biscuit bench`
//! binary reports; the binary remains the source of the paper's CSV.

use biscuit_auth::KeyPair;
use criterion::{criterion_group, criterion_main, Criterion};
use e1_biscuit::{authorize_once, build_token_bytes, epoch_of, HopCaveats};

fn depth4_hops() -> Vec<HopCaveats> {
    // Mirrors the workload's narrowing schedule for depth 4, fixed window.
    let from = "2026-07-10T00:00:00Z".to_string();
    let until = "2026-07-11T00:00:00Z".to_string();
    (0..4)
        .map(|i| {
            let seg: String = (1..=i).map(|k| format!("/seg{}", k)).collect();
            let prefix = if i == 0 {
                "https://api.foo.com/".to_string()
            } else {
                format!("https://api.foo.com{}", seg)
            };
            HopCaveats {
                max_per_call_micro: 1_000_000 - (i as i64) * 50_000,
                daily_limit_micro: 10_000_000 - (i as i64) * 200_000,
                window_seconds: 3600 + (i as i64) * 600,
                valid_from: from.clone(),
                valid_until: until.clone(),
                endpoint_prefixes: vec![prefix],
            }
        })
        .collect()
}

fn bench_authorize(c: &mut Criterion) {
    let root = KeyPair::new();
    let pubk = root.public();
    let hops = depth4_hops();
    let bytes = build_token_bytes(&hops, "EU", &root);
    let url = "https://api.foo.com/seg1/seg2/seg3/res";
    let at = epoch_of("2026-07-10T12:00:00Z");

    c.bench_function("biscuit_authorize_depth4", |b| {
        b.iter(|| {
            let ok = authorize_once(
                std::hint::black_box(&bytes),
                pubk,
                500_000,
                std::hint::black_box(url),
                at,
                "EU",
            );
            assert!(ok);
        })
    });
}

criterion_group!(benches, bench_authorize);
criterion_main!(benches);
