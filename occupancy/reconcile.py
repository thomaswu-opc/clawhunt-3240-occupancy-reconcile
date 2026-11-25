"""对账：按日重算出租率，与驾驶舱返回值逐日比对，超过阈值输出明细。

阈值是 **0.1 个百分点**（即 0.001 的比率差），用比率算完再乘 100 比较，避免浮点比较时的
"0.1 到底算不算超过"这类争议：判定式写成 `abs(diff) * 100 > 0.1`，恰好 0.1 不算超。
明细必须带"为什么是这一天"的证据：当天的可租座位日、已租座位日、以及贡献占用的租约 id。
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from occupancy.calc import daily, monthly
from occupancy.models import Lease, Maintenance, Unit

THRESHOLD_PP = 0.1


def reconcile(
    units: list[Unit],
    leases: list[Lease],
    maintenance: list[Maintenance],
    month_start: date,
    dashboard_rates: dict[date, float],
    threshold_pp: float = THRESHOLD_PP,
    log_path: str | Path | None = None,
) -> dict:
    rows = daily(units, leases, maintenance, month_start)
    details: list[dict] = []

    for row in rows:
        if row.day not in dashboard_rates:
            continue
        actual = dashboard_rates[row.day]
        # 先四舍五入到 1e-6 个百分点再比：0.5 - 0.501 在浮点里是 0.10000000000000005，
        # 直接比较会把"恰好 0.1pp"误判成超标（这一条有专门的边界用例）。
        diff_pp = round(abs(row.rate - actual) * 100, 6)
        if diff_pp > threshold_pp:
            details.append({
                "stat_date": row.day.isoformat(),
                "expected_rate": round(row.rate, 6),
                "actual_rate": round(actual, 6),
                "diff_pp": round(diff_pp, 4),
                "available_seat_days": row.available,
                "occupied_seat_days": row.occupied,
                "lease_ids": row.lease_ids,
            })

    summary = monthly(rows)
    summary["checked_days"] = sum(1 for r in rows if r.day in dashboard_rates)
    summary["mismatch_days"] = len(details)
    result = {"month": month_start.strftime("%Y-%m"), "summary": summary, "details": details}

    if log_path:
        p = Path(log_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"kind": "reconcile", **result}, ensure_ascii=False) + "\n")
    return result
