//! E1 Biscuit treatment — shared logic (used by the CSV bench binary and the
//! criterion micro-bench).
//!
//! Builds an attenuated Biscuit chain from the canonical workload fixture and
//! runs the exercise-time authorize path. The caveats expressed as Biscuit
//! Datalog checks are the SAME semantics the fixture carries and the same the
//! grant@1 and Rego consumers enforce:
//!
//!   * `check if amount($a), $a <= CAP`          (per-call cap, micro-USD i64)
//!   * `check if resource($r), $r.starts_with(P)` (endpoint prefix)
//!   * `check if time($t), $t >= FROM`            (validity window start)
//!   * `check if time($t), $t <= UNTIL`           (validity window end)
//!   * `check if jurisdiction(J)`                 (authority block only)
//!
//! MONOTONE FRAGMENT: only conjunctive, negation-free checks are used, and
//! attenuation is by APPENDING blocks (a Biscuit block can only add checks,
//! never remove a parent's), so a child chain's admitted (url, amount, time)
//! set is a subset of its parent's by construction — Property 1 of the paper.
//! No `deny`/negation caveat is emitted here.
//!
//! DOCUMENTED DIVERGENCE: Biscuit's `starts_with` is a raw string-prefix test,
//! whereas grant@1 / Rego match on a URL path/host boundary. The workload never
//! exercises a boundary-confusion URL in the cross-system gate (the out_of_prefix
//! violation uses a different host, which all three reject identically), so this
//! divergence cannot cause a verdict disagreement here. It is called out in the
//! README under "Semantic equivalence".

use biscuit_auth::macros::{authorizer, biscuit, block};
use biscuit_auth::{AuthorizerLimits, Biscuit, KeyPair, PublicKey};
use serde::Deserialize;
use std::time::Duration;

#[derive(Deserialize, Clone)]
pub struct HopCaveats {
    pub max_per_call_micro: i64,
    pub daily_limit_micro: i64,
    pub window_seconds: i64,
    pub valid_from: String,
    pub valid_until: String,
    pub endpoint_prefixes: Vec<String>,
}

#[derive(Deserialize, Clone)]
pub struct Chain {
    pub chain_index: u32,
    pub hops: Vec<HopCaveats>,
}

#[derive(Deserialize, Clone)]
pub struct Exercise {
    pub id: u64,
    pub chain_index: u32,
    pub resource_url: String,
    pub amount_micro: i64,
    pub at: String,
    pub jurisdiction: String,
    pub expect: String,
    pub violation: Option<String>,
}

#[derive(Deserialize)]
pub struct Fixture {
    pub depth: u32,
    pub fanout: u32,
    pub jurisdiction: String,
    pub n_allow_exercises: u64,
    pub n_violation_exercises: u64,
    pub chains: Vec<Chain>,
    pub exercises: Vec<Exercise>,
}

/// Parse our own fixed-format "YYYY-MM-DDTHH:MM:SSZ" into epoch seconds.
pub fn epoch_of(rfc: &str) -> i64 {
    let n = |s: usize, e: usize| rfc[s..e].parse::<i64>().unwrap();
    let (y, mo, d) = (n(0, 4), n(5, 7), n(8, 10));
    let (h, mi, s) = (n(11, 13), n(14, 16), n(17, 19));
    // Howard Hinnant days_from_civil.
    let yy = if mo <= 2 { y - 1 } else { y };
    let era = if yy >= 0 { yy } else { yy - 399 } / 400;
    let yoe = yy - era * 400;
    let doy = (153 * (if mo > 2 { mo - 3 } else { mo + 9 }) + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    let days = era * 146097 + doe - 719468;
    days * 86400 + h * 3600 + mi * 60 + s
}

/// Build the attenuated Biscuit token bytes for one chain. Authority block =
/// hop 0 (with the jurisdiction check); each subsequent hop is an appended block.
pub fn build_token_bytes(hops: &[HopCaveats], jurisdiction: &str, root: &KeyPair) -> Vec<u8> {
    let h0 = &hops[0];
    let mut token = biscuit!(
        r#"
        check if amount($a), $a <= {cap};
        check if resource($r), $r.starts_with({prefix});
        check if time($t), $t >= {vfrom};
        check if time($t), $t <= {vuntil};
        check if jurisdiction({jur});
    "#,
        cap = h0.max_per_call_micro,
        prefix = h0.endpoint_prefixes[0].clone(),
        vfrom = epoch_of(&h0.valid_from),
        vuntil = epoch_of(&h0.valid_until),
        jur = jurisdiction.to_string(),
    )
    .build(root)
    .expect("build authority block");

    for h in &hops[1..] {
        token = token
            .append(block!(
                r#"
                check if amount($a), $a <= {cap};
                check if resource($r), $r.starts_with({prefix});
                check if time($t), $t >= {vfrom};
                check if time($t), $t <= {vuntil};
            "#,
                cap = h.max_per_call_micro,
                prefix = h.endpoint_prefixes[0].clone(),
                vfrom = epoch_of(&h.valid_from),
                vuntil = epoch_of(&h.valid_until),
            ))
            .expect("append attenuation block");
    }
    token.to_vec().expect("serialize token")
}

/// The realistic exercise path: deserialize the token (VERIFIES all block
/// signatures against the root public key) and run the authorizer with the
/// exercise facts. Returns true iff ALLOW. This mirrors grant@1's per-exercise
/// `verify_chain` (crypto per hop) + `check_payment` (policy) — both systems
/// re-verify signatures AND evaluate policy on every exercise.
#[inline]
pub fn authorize_once(
    bytes: &[u8],
    root_pub: PublicKey,
    amount: i64,
    url: &str,
    at: i64,
    jur: &str,
) -> bool {
    let token = match Biscuit::from(bytes, root_pub) {
        Ok(t) => t,
        Err(_) => return false,
    };
    let built = authorizer!(
        r#"
        amount({amount});
        resource({url});
        time({at});
        jurisdiction({jur});
        allow if true;
    "#,
        amount = amount,
        url = url.to_string(),
        at = at,
        jur = jur.to_string(),
    )
    .build(&token);
    let mut a = match built {
        Ok(a) => a,
        Err(_) => return false,
    };
    // Raise the datalog time budget well above Biscuit's 1ms default. That
    // default is a DoS guard, not a policy: under a loaded sandbox a legitimate
    // deep-chain authorize can exceed 1ms and spuriously return a timeout error
    // (which would look like a DENY and corrupt the correctness gate). A
    // benchmark must measure the real work, not trip the guard — so we give a
    // generous ceiling and let the wall clock report the true latency.
    let limits = AuthorizerLimits {
        max_time: Duration::from_secs(10),
        ..Default::default()
    };
    a.authorize_with_limits(limits).is_ok()
}
