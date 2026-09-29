# syntax=docker/dockerfile:1.27.0@sha256:bde3983e9c939224420ddaf6b784cc30e09b035a4dea01f581230c50809f372e
#
# Lab C (Cloud Solutions, WS 2026/27): pinned E1 harness image.
#
# Source: computational-jurisprudence-eval at tag v2-fi-revision-2026-08-11
# (06db5fc496958a03bc02f72f370f0a8f7d697bc7). Only lab-c/ and the CI workflow
# are added on top of the tag; CI checks that nothing else differs.
#
# Build from the repository root, natively on each architecture (no QEMU):
#   docker buildx build -f lab-c/Dockerfile --platform linux/<arch> .
#
# Version choices the tag does not pin (owner decision, 2026-09-29):
#   OPA 1.18.2 (the version every results/ CSV records), toxiproxy 2.12.0
#   (scripts/run-cloud-x86.sh), CPython 3.11.15, two-way gate (Biscuit, OPA).

ARG SOURCE_DATE_EPOCH=1786461678
ARG PYTHON_IMAGE=docker.io/library/python:3.11.15-slim-trixie@sha256:90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff
ARG RUST_IMAGE=docker.io/library/rust:1.96.1-slim-trixie@sha256:31ee7fc65186be7e0e0ccb3f2ca305f14e4739e7642a1ae65753aa5d7b874523

# --- pinned third-party binaries: exact version, SHA-256 checked by BuildKit --
# One stage per architecture; only the one matching TARGETARCH is built.
FROM scratch AS bin-amd64
ADD --checksum=sha256:9903e5125ac281104f2c4b7371d10cc3b74a98933743fcbfc174f9bf0ab20de8 \
    https://github.com/open-policy-agent/opa/releases/download/v1.18.2/opa_linux_amd64_static /opa
ADD --checksum=sha256:556d891134a3c582dc1e1a3f7335fd55142e5965769855a00b944e13e48302fc \
    https://github.com/Shopify/toxiproxy/releases/download/v2.12.0/toxiproxy-server-linux-amd64 /toxiproxy-server

FROM scratch AS bin-arm64
ADD --checksum=sha256:9cad2e67d375aded483823349173fe100d9701d37635908edadeb0298603c58c \
    https://github.com/open-policy-agent/opa/releases/download/v1.18.2/opa_linux_arm64_static /opa
ADD --checksum=sha256:53e770c1c3035b5a9f1bc629fce537db1f95f62b26f4ebe6e756afd701cf077c \
    https://github.com/Shopify/toxiproxy/releases/download/v2.12.0/toxiproxy-server-linux-arm64 /toxiproxy-server

FROM bin-${TARGETARCH} AS bin

# --- Biscuit bench: built from Cargo.lock with the pinned toolchain -----------
FROM ${RUST_IMAGE} AS build
ARG SOURCE_DATE_EPOCH
ENV SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH} \
    CARGO_INCREMENTAL=0
WORKDIR /src
COPY rust-toolchain.toml Cargo.toml Cargo.lock ./
COPY crates ./crates
# rust-toolchain.toml asks for 1.96.1, which is the image's toolchain, so rustup
# downloads nothing; --locked refuses any change to Cargo.lock.
RUN test "$(rustc --version | cut -d' ' -f2)" = "1.96.1" \
 && cargo build --release --locked -p e1-biscuit \
 && install -D -m 0755 target/release/e1-biscuit /stage/e1-biscuit

# --- runtime ------------------------------------------------------------------
FROM ${PYTHON_IMAGE}
ARG SOURCE_DATE_EPOCH
ARG TARGETARCH

# Nothing is installed on top of the base image: the harness's only extra
# tool, curl, is replaced by lab-c/curl-loopback.py (stdlib, loopback only).

# Harness at the tag: only what the E1 gate, sweep and table generator read.
# The table generator's reference directory: the Mac-mini rows that
# `mkcrossplatform.py results ...` resolves to at the tag (its loader keeps the
# last file per key in name order), named explicitly so nothing else can win.
COPY --chmod=0755 scripts/opa_e1.sh /opt/harness/scripts/opa_e1.sh
COPY python/common.py python/opa_bench.py python/verify_gate_2way.py python/mkcrossplatform.py /opt/harness/python/
COPY policies/capability.rego /opt/harness/policies/
COPY workloads/ /opt/harness/workloads/
COPY results/e1-biscuit_pier39.local_20260710T230124Z.csv \
     results/e1-opa_pier39.local_20260711T135215Z.csv \
     /opt/harness/reference/

COPY --from=build /stage/e1-biscuit /usr/local/bin/e1-biscuit
COPY --from=bin --chmod=0755 /opa /usr/local/libexec/lab-c/opa
COPY --from=bin --chmod=0755 /toxiproxy-server /usr/local/bin/toxiproxy-server
COPY --chmod=0755 lab-c/opa-wrapper.sh /opt/harness/bin/opa
COPY --chmod=0755 lab-c/curl-loopback.py /opt/harness/bin/curl
COPY --chmod=0755 lab-c/entrypoint.sh /opt/lab-c/entrypoint.sh
COPY lab-c/platform_info.py lab-c/sanitize.py lab-c/audit_imports.py /opt/lab-c/

RUN set -eu; \
    case "${TARGETARCH}" in amd64) a=x86_64 ;; arm64) a=aarch64 ;; *) exit 1 ;; esac; \
    printf '%s\n' "$a" > /opt/lab-c/image-arch; \
    test "$(uname -m)" = "$a"; \
    cd /opt/harness; \
    mkdir workloads-f1 workloads-smoke; \
    for f in workloads/graph_d*_f1.json; do ln -s "../$f" workloads-f1/; done; \
    ln -s ../workloads/graph_d4_f1.json workloads-smoke/; \
    python3 /opt/lab-c/audit_imports.py; \
    python3 -m compileall -q --invalidation-mode unchecked-hash /opt/harness/python /opt/lab-c; \
    /usr/local/libexec/lab-c/opa version | grep -qx 'Version: 1.18.2'; \
    /usr/local/bin/toxiproxy-server -version | grep -q '2\.12\.0'; \
    mkdir -m 0755 /out

LABEL org.opencontainers.image.source="https://github.com/vstantch/computational-jurisprudence-eval" \
      org.opencontainers.image.revision="06db5fc496958a03bc02f72f370f0a8f7d697bc7" \
      org.opencontainers.image.version="ws2026" \
      org.opencontainers.image.title="cj-lab-c" \
      org.opencontainers.image.description="Lab C: E1 harness (Biscuit vs OPA, toxiproxy) at v2-fi-revision-2026-08-11. Homework image; results are not research data."

ENV SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH} \
    HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/harness/bin:/usr/local/bin:/usr/bin:/bin

USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["/opt/lab-c/entrypoint.sh"]
CMD ["help"]
