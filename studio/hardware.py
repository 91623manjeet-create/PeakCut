"""How much processor the machine really has.

Windows and macOS report "processors" as the number of threads the processor can run at once, and on most laptops
that is twice the number of real cores: the second thread of a core shares its arithmetic units, so it adds a
little speed, not another core. Sizing work by that number is what makes a small laptop try to do twice as much as
it can, so the rest of PeakCut asks here for the number of real cores.

Nothing here needs any extra package, and every part has a fallback: a machine we cannot measure is treated as
having half as many cores as threads, or one core when that is not a whole number.
"""
import os
import sys


def logical_cores() -> int:
    return max(1, os.cpu_count() or 1)


def _windows() -> int:
    import ctypes

    class _Info(ctypes.Structure):
        # SYSTEM_LOGICAL_PROCESSOR_INFORMATION: a mask, a relationship, then a union that is 16 bytes wide.
        _fields_ = [("mask", ctypes.c_size_t), ("relationship", ctypes.c_int), ("reserved", ctypes.c_ulonglong * 2)]

    size = ctypes.sizeof(_Info)
    need = ctypes.c_ulong(0)
    kernel32 = ctypes.windll.kernel32
    if not kernel32.GetLogicalProcessorInformation(None, ctypes.byref(need)) and not need.value:
        return 0
    count = need.value // size
    if count <= 0:
        return 0
    buf = (_Info * count)()
    if not kernel32.GetLogicalProcessorInformation(buf, ctypes.byref(need)):
        return 0
    got = need.value // size
    # Relationship 0 is RelationProcessorCore: one real core, whatever the number of threads on it.
    return sum(1 for i in range(got) if buf[i].relationship == 0)


def _linux() -> int:
    # Counting the "core id" pairs (socket, core) is exact even when the processor reports itself oddly.
    cores = set()
    try:
        with open("/proc/cpuinfo", encoding="ascii", errors="replace") as f:
            pkg, core = 0, None
            for line in f:
                k, _, v = line.partition(":")
                k, v = k.strip(), v.strip()
                if k == "physical id":
                    pkg = int(v)
                elif k == "core id":
                    core = int(v)
                elif not line.strip():
                    if core is not None:
                        cores.add((pkg, core))
                    pkg, core = 0, None
            if core is not None:
                cores.add((pkg, core))
    except OSError:
        pass
    return len(cores)


def _mac() -> int:
    try:
        import subprocess
        out = subprocess.run(["sysctl", "-n", "hw.physicalcpu"], capture_output=True, text=True, timeout=3)
        return int(out.stdout.strip() or 0)
    except Exception:  # noqa: BLE001 - no sysctl, or it was refused: fall back below
        return 0


_known = None


def physical_cores() -> int:
    """The number of real cores, cached: it never changes while PeakCut runs."""
    global _known
    if _known:
        return _known
    got = 0
    try:
        if sys.platform.startswith("win"):
            got = _windows()
        elif sys.platform == "darwin":
            got = _mac()
        else:
            got = _linux()
    except Exception:  # noqa: BLE001 - a system we cannot read: the guess below is close enough
        got = 0
    threads = logical_cores()
    if not 0 < got <= threads:
        got = max(1, threads // 2) if threads > 2 else threads
    _known = got
    return got
