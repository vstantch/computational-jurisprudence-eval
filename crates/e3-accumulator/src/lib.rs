//! E3 — Accumulator revocation microbenchmark. **SKELETON ONLY (cut-first).**
//!
//! Per the plan (§1 E3, "optional, cut first if time slips") E3 is deliberately
//! *not implemented* in this pass. This crate exists to (a) record the crate
//! choice and rationale as a committed decision, and (b) give the Mac-mini
//! follow-up a compiling seam to fill. Nothing here is wired into any bench and
//! no number it could produce enters the paper until it is actually measured
//! (integrity rule: measured, never estimated).
//!
//! ## Crate choice: `vb_accumulator` (Dock Network)
//!
//! See `Cargo.toml` for the full justification. In one line: it is a maintained
//! universal pairing-based accumulator giving membership **and non-membership**
//! witnesses plus batch witness-update (`Omega`) and public/epoch-root updates —
//! exactly the surface E3 must time. The crates.io crate literally named
//! `accumulator` is an unrelated key-value store and is the wrong artifact.
//!
//! ## What the Mac-mini run must measure (plan §1 E3), left as `todo!()`:
//!
//! * non-membership proof generation and verification latency;
//! * witness-update cost after BATCH revocations of 10^2, 10^3, 10^4;
//! * epoch-root (public accumulator) update cost.
//!
//! Each becomes one *measured* row replacing a borrowed Table-1 row in the paper.

/// Batch sizes E3 will sweep (revocations per epoch). Declared now so the paper
/// skeleton and the eventual bench agree on the x-axis.
pub const REVOCATION_BATCH_SIZES: [usize; 3] = [100, 1_000, 10_000];

/// Marker that E3 is intentionally unimplemented in this pass. Referenced by the
/// harness/README so "E3 = skeleton" is a checkable fact, not a silent gap.
pub const E3_STATUS: &str = "skeleton-only (cut-first); crate=vb_accumulator; not wired";

/// Placeholder for the non-membership timing entry point. Wiring this against
/// `vb_accumulator`'s `NonMembershipWitness` / `Accumulator` API is the
/// Mac-mini follow-up; it MUST NOT return a fabricated latency.
pub fn measure_non_membership() -> ! {
    unimplemented!(
        "E3 is cut-first: implement against vb_accumulator on the Mac mini and \
         report only measured latencies (see module docs)."
    )
}
