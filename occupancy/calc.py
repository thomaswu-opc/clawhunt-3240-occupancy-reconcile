"""出租率计算：纯函数，输入一组事实，输出按日与按月的口径值。

之所以不直接写 SQL：口径有五个边界（月中起租、月中退租、维修、共享空间、续约衔接），
写成纯函数才能用手算数字逐日验，也才能让对账脚本在不连驾驶舱的情况下复现同一结果。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from occupancy.models import Lease, Maintenance, Unit, month_days


@dataclass
class DayResult:
    day: date
    available: int      # 可租座位日
    occupied: int       # 已租座位日
    lease_ids: list[str]

    @property
    def rate(self) -> float:
        return (self.occupied / self.available) if self.available else 0.0


def daily(units: list[Unit], leases: list[Lease], maintenance: list[Maintenance],
          month_start: date) -> list[DayResult]:
    out: list[DayResult] = []
    for day in month_days(month_start):
        blocked = {m.unit_id for m in maintenance if m.covers(day)}
        available = sum(u.capacity for u in units if u.id not in blocked)
        hit = [le for le in leases if le.covers(day)]
        occupied = sum(le.seats for le in hit)
        out.append(DayResult(day=day, available=available, occupied=occupied,
                             lease_ids=sorted(le.id for le in hit)))
    return out


def monthly(rows: list[DayResult]) -> dict:
    """累计口径：Σ已租 / Σ可租。不是日均出租率的算术平均（两者在分母变化时不等价）。"""
    occ = sum(r.occupied for r in rows)
    avail = sum(r.available for r in rows)
    return {
        "days": len(rows),
        "occupied_seat_days": occ,
        "available_seat_days": avail,
        "rate": (occ / avail) if avail else 0.0,
    }
