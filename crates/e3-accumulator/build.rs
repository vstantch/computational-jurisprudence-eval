//! Records the version of the rustc that compiles this crate, so the CSV
//! `runtime` column reports the compiler actually used (e.g. "rustc-1.96.1").

use std::process::Command;

fn main() {
    let rustc = std::env::var("RUSTC").unwrap_or_else(|_| "rustc".into());
    let out = Command::new(rustc)
        .arg("--version")
        .output()
        .expect("run rustc --version");
    let text = String::from_utf8(out.stdout).expect("rustc --version is UTF-8");
    // "rustc 1.96.1 (31fca3adb 2026-06-26)" -> "1.96.1"
    let version = text.split_whitespace().nth(1).expect("rustc version field");
    println!("cargo:rustc-env=PCT_RUSTC_VERSION={version}");
    println!("cargo:rerun-if-env-changed=RUSTC");
}
