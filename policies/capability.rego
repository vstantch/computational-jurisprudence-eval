# PCT-eval E1 — OPA/Rego centralized-PDP baseline policy.
#
# Published deliberately (plan §5 risk row: "OPA baseline accused of
# strawmanning -> publish the Rego policy"). This policy expresses EXACTLY the
# same caveat semantics the Biscuit token checks and the capability-grant@1
# fragment enforce, evaluated over the SAME canonical workload input document:
#
#   * per-call cap        amount <= every hop's max_per_call_micro  (== <= min)
#   * endpoint prefix     resource_url falls under every hop's prefix set,
#                         matched on a URL host/path boundary (the same rule as
#                         presidio_x402.policy_engine._endpoint_prefix_matches)
#   * validity window     valid_from <= at <= valid_until for every hop
#   * jurisdiction        exercise.jurisdiction == the graph jurisdiction J
#
# The PDP evaluates the FULL chain and computes the intersection itself (the
# `every hop` quantifiers), so it makes the same ALLOW/DENY decision grant@1's
# `_intersect` + `check_payment` and Biscuit's all-blocks-must-pass make.
#
# Scope note (honest baseline, NOT a strawman): this policy models the PDP
# *decision*. It does NOT re-verify Ed25519 signatures — a centralized PDP
# evaluates policy over an input it trusts, and the paper's claim under test is
# the ROUND-TRIP + availability cost, not raw crypto speed. Giving OPA LESS work
# (no signature check) biases the comparison in OPA's favour, which is the
# conservative direction for our thesis. Stated here so a reviewer sees it.
#
# Amounts are integer micro-USD (no float, matching the rest of the pipeline).
# Requires OPA >= 0.59 (rego.v1 keywords). Query: data.pct.allow

package pct

import rego.v1

default allow := false

# --- per-call cap: amount must satisfy EVERY hop (equivalent to <= tightest) ---
amount_ok if {
	every hop in input.chain {
		input.exercise.amount_micro <= hop.max_per_call_micro
	}
}

# --- endpoint prefix: URL host/path boundary match, same as the Python matcher ---
prefix_matches(prefix, url) if {
	base := trim_suffix(prefix, "/")
	url == base
}

prefix_matches(prefix, url) if {
	base := trim_suffix(prefix, "/")
	startswith(url, concat("", [base, "/"]))
}

hop_prefix_ok(hop) if {
	some p in hop.endpoint_prefixes
	prefix_matches(p, input.exercise.resource_url)
}

prefix_ok if {
	every hop in input.chain {
		hop_prefix_ok(hop)
	}
}

# --- validity window: at within EVERY hop's [valid_from, valid_until] ---
time_ok if {
	at_ns := time.parse_rfc3339_ns(input.exercise.at)
	every hop in input.chain {
		at_ns >= time.parse_rfc3339_ns(hop.valid_from)
		at_ns <= time.parse_rfc3339_ns(hop.valid_until)
	}
}

# --- jurisdiction equality (Biscuit + Rego check it; grant@1's @1 fragment omits
# it, so J is held constant across the workload — see README "Semantic
# equivalence"). ---
jurisdiction_ok if {
	input.exercise.jurisdiction == input.jurisdiction
}

allow if {
	amount_ok
	prefix_ok
	time_ok
	jurisdiction_ok
}
