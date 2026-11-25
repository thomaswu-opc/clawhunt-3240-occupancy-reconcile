"""出租率的数据结构与口径声明。

口径固定写成一句话，避免每次对账都重新解释：
**出租率 = 已租座位日 / 可租座位日**，按日累计，月末用累计值（不是日均值的平均）。

三条容易被实现写错的约定：
1. 租约区间是**左闭右开** `[start, end)`：月中退租当天不计入占用，下一位租客当天可起租，
   续约因此天然无缝、也不会重复计数；
2. 维修中的工位从**可租**里扣，不是从已租里扣 —— 分母变小，出租率会上升，这是业务口径；
3. 共享空间按**座位容量**折算：占 4 个座位就是 4，不是"占用 1 个空间"。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

DESK = "desk"
SHARED = "shared"


@dataclass(frozen=True)
class Unit:
    id: str
    kind: str          # desk / shared
    capacity: int      # desk 恒为 1；shared 为可售座位数

    def __post_init__(self) -> None:
        if self.kind not in (DESK, SHARED):
            raise ValueError("unknown_unit_kind:%s" % self.kind)
        if self.capacity < 1:
            raise ValueError("capacity_must_be_positive")


@dataclass(frozen=True)
class Lease:
    id: str
    unit_id: str
    seats: int
    start: date
    end: date          # 左闭右开

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError("lease %s: end must be after start" % self.id)
        if self.seats < 1:
            raise ValueError("lease %s: seats must be >= 1" % self.id)

    def covers(self, day: date) -> bool:
        return self.start <= day < self.end


@dataclass(frozen=True)
class Maintenance:
    unit_id: str
    start: date
    end: date          # 左闭右开

    def covers(self, day: date) -> bool:
        return self.start <= day < self.end


def month_days(month_start: date) -> list[date]:
    """返回该月每一天。month_start 必须是 1 号。"""
    if month_start.day != 1:
        raise ValueError("month_start must be the 1st")
    nxt = date(month_start.year + (month_start.month == 12),
               1 if month_start.month == 12 else month_start.month + 1, 1)
    days, cur = [], month_start
    while cur < nxt:
        days.append(cur)
        cur += timedelta(days=1)
    return days
