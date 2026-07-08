from __future__ import annotations

import ctypes
import os
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path


PERFORMANCE_MODES = ("safe", "balanced", "max")
PERFORMANCE_LABELS = {
    "safe": "Seguro",
    "balanced": "Balanceado",
    "max": "Maximo",
}


@dataclass(frozen=True)
class HardwareProfile:
    processor: str
    logical_cpus: int
    ram_gb: float | None

    def workers_for(self, mode: str) -> int:
        cpus = max(1, self.logical_cpus)
        if mode == "safe":
            return max(1, min(2, cpus // 2 or 1))
        if mode == "balanced":
            return max(1, min(4, cpus // 2 or 1))
        if mode == "max":
            return cpus
        raise ValueError(f"modo de performance desconhecido: {mode}")

    def summary(self, mode: str) -> str:
        ram = f"{self.ram_gb:.1f} GB RAM" if self.ram_gb is not None else "RAM indisponivel"
        return f"{self.logical_cpus} threads logicos | {ram} | workers {self.workers_for(mode)}"


@dataclass(frozen=True)
class DiskUsage:
    path: str
    total_gb: float
    used_gb: float
    free_gb: float
    used_percent: float

    def summary(self) -> str:
        return f"{self.used_percent:.1f}% usado | {self.used_gb:.1f} GB usados | {self.free_gb:.1f} GB livres"


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def total_ram_gb() -> float | None:
    if os.name != "nt":
        return None
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return status.ullTotalPhys / (1024**3)


def detect_hardware() -> HardwareProfile:
    logical = os.cpu_count() or 1
    processor = platform.processor() or platform.machine() or "processador desconhecido"
    return HardwareProfile(processor=processor, logical_cpus=logical, ram_gb=total_ram_gb())


def disk_usage_for(path: str | Path) -> DiskUsage:
    target = Path(path).expanduser()
    usage = shutil.disk_usage(target if target.exists() else target.anchor or target.parent)
    total = usage.total / (1024**3)
    free = usage.free / (1024**3)
    used = usage.used / (1024**3)
    percent = (used / total * 100) if total else 0.0
    return DiskUsage(path=str(target), total_gb=total, used_gb=used, free_gb=free, used_percent=percent)


def normalize_performance_mode(value: str | None) -> str:
    if not value:
        return "balanced"
    normalized = value.strip().lower()
    aliases = {
        "seguro": "safe",
        "safe": "safe",
        "balanceado": "balanced",
        "balanced": "balanced",
        "max": "max",
        "maximo": "max",
        "maximum": "max",
    }
    if normalized not in aliases:
        raise ValueError(f"modo de performance desconhecido: {value}")
    return aliases[normalized]
