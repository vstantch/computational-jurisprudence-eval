"""Platform facts for Lab C, limited to what the handout allows.

The only facts this module ever emits are:
  arch         uname -m inside the container
  cpu_model    CPU model string (x86: /proc/cpuinfo "model name";
               arm64: vendor and part number from the MIDR fields)
  cores        CPUs available to the container
  os           kernel name (uname -s, lower-case)
  kernel       kernel release (uname -r)
  virtualised  "yes", "no" or "unknown"

It never reads serial numbers, MAC addresses, the hostname, or user names. DMI
vendor strings are read only to decide "virtualised" and are not emitted.

Usage:
  platform_info.py json <out_path>   write the facts above as JSON
  platform_info.py cpu               print cpu_model (for PCT_CPU)
  platform_info.py check-native      exit 0 only if the image runs natively
"""

from __future__ import annotations

import json
import os
import platform
import sys

IMAGE_ARCH_FILE = "/opt/lab-c/image-arch"

ARM_VENDORS = {
    "0x41": "ARM", "0x42": "Broadcom", "0x43": "Cavium", "0x46": "Fujitsu",
    "0x48": "HiSilicon", "0x4e": "NVIDIA", "0x50": "APM", "0x51": "Qualcomm",
    "0x61": "Apple", "0x6d": "Microsoft", "0xc0": "Ampere",
}
ARM_LTD_PARTS = {
    "0xd08": "Cortex-A72", "0xd0b": "Cortex-A76", "0xd0c": "Neoverse-N1",
    "0xd40": "Neoverse-V1", "0xd49": "Neoverse-N2", "0xd4f": "Neoverse-V2",
}
VM_DMI_VENDORS = (
    "qemu", "kvm", "vmware", "microsoft corporation", "xen", "amazon ec2",
    "google", "innotek", "parallels", "bochs", "oracle", "apple virtualization",
)
VM_KERNEL_MARKERS = ("linuxkit", "orbstack", "microsoft-standard", "wsl2")


def _read(path: str) -> str:
    try:
        with open(path, errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _cpuinfo() -> list[tuple[str, str]]:
    pairs = []
    for line in _read("/proc/cpuinfo").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            pairs.append((k.strip().lower(), v.strip()))
    return pairs


def kernel_arch() -> str:
    """The architecture of the kernel, from the format of /proc/cpuinfo.

    uname -m reports the emulated machine under QEMU user mode or Rosetta, but
    /proc/cpuinfo is the host kernel's and keeps the host's format.
    """
    keys = {k for k, _ in _cpuinfo()}
    if "vendor_id" in keys or "flags" in keys:
        return "x86_64"
    if "cpu implementer" in keys or "features" in keys:
        return "aarch64"
    return "unknown"


def _clean(s: str) -> str:
    # The harness writes PCT_CPU into CSV rows unquoted: no commas, no newlines.
    return " ".join(s.replace(",", " ").split())[:120] or "unknown"


def cpu_model() -> str:
    info = _cpuinfo()
    for k, v in info:
        if k == "model name" and v:
            return _clean(v)
    vendors = sorted({v.lower() for k, v in info if k == "cpu implementer"})
    parts = sorted({v.lower() for k, v in info if k == "cpu part"})
    if vendors:
        vendor = " / ".join(ARM_VENDORS.get(v, f"implementer {v}") for v in vendors)
        if vendors == ["0x41"] and parts and all(p in ARM_LTD_PARTS for p in parts):
            names = " + ".join(ARM_LTD_PARTS[p] for p in parts)
            return _clean(f"ARM {names}")
        return _clean(f"{vendor} part {'+'.join(parts) or 'unknown'}")
    return "unknown"


def cores() -> int:
    try:
        return len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return os.cpu_count() or 0


def virtualised() -> str:
    flags = " ".join(v for k, v in _cpuinfo() if k == "flags").split()
    if "hypervisor" in flags:
        return "yes"
    if _read("/sys/hypervisor/type").strip():
        return "yes"
    if os.path.exists("/proc/device-tree/hypervisor"):
        return "yes"
    dmi = " ".join(
        _read(f"/sys/class/dmi/id/{f}").strip().lower()
        for f in ("sys_vendor", "product_name", "bios_vendor")
    )
    if any(m in dmi for m in VM_DMI_VENDORS):
        return "yes"
    if any(m in platform.release().lower() for m in VM_KERNEL_MARKERS):
        return "yes"
    # x86 exposes the hypervisor bit to guests; its absence is informative.
    if kernel_arch() == "x86_64" and flags:
        return "no"
    return "unknown"


def facts() -> dict:
    return {
        "arch": platform.machine(),
        "cpu_model": cpu_model(),
        "cores": cores(),
        "os": platform.system().lower(),
        "kernel": platform.release(),
        "virtualised": virtualised(),
    }


def image_arch() -> str:
    return _read(IMAGE_ARCH_FILE).strip()


def check_native() -> int:
    want, uname_m, kern = image_arch(), platform.machine(), kernel_arch()
    if uname_m != want:
        print(f"lab-c: REFUSING TO TIME: uname -m is {uname_m}, image is {want}")
        return 1
    if kern != want:
        print(f"lab-c: REFUSING TO TIME: the {want} image is emulated on an "
              f"{kern} kernel (QEMU or Rosetta); timings would be meaningless")
        return 1
    print(f"lab-c: native {want}: uname -m and kernel agree with the image")
    return 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "json" and len(sys.argv) == 3:
        with open(sys.argv[2], "w") as f:
            json.dump(facts(), f, indent=2, sort_keys=True)
            f.write("\n")
        return 0
    if cmd == "cpu":
        print(cpu_model())
        return 0
    if cmd == "check-native":
        return check_native()
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
