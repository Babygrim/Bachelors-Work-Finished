import ctypes
import subprocess
import threading
import time


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def process_memory_bytes():
    if not hasattr(ctypes, "windll"):
        return None
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    process = ctypes.windll.kernel32.GetCurrentProcess()
    get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
    if not get_memory(process, ctypes.byref(counters), counters.cb):
        return None
    return int(counters.WorkingSetSize)


_gpu_memory_lock = threading.Lock()
_gpu_memory_cache = (0.0, None)


def gpu_memory_bytes():
    global _gpu_memory_cache
    now = time.monotonic()
    with _gpu_memory_lock:
        if now - _gpu_memory_cache[0] < 1.0:
            return _gpu_memory_cache[1]
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.used",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                check=True,
                text=True,
                timeout=0.25,
            )
            value = sum(
                int(line.strip()) for line in result.stdout.splitlines() if line.strip()
            )
            memory = value * 1024 * 1024
        except (
            FileNotFoundError,
            OSError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            ValueError,
        ):
            memory = None
        _gpu_memory_cache = (now, memory)
        return memory
