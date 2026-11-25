#!/usr/bin/env python3
"""每月初的对账入口：读事实数据 + 驾驶舱返回值，逐日比对，超阈值输出明细并写日志。

用法：
    python run_reconcile.py --data sample_data.json --dashboard dashboard_2026-11.json \
        --month 2026-11 --log logs/reconcile.log

退出码：0 = 无差异；1 = 有差异（便于 cron 里直接告警）。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from occupancy.models import Lease, Maintenance, Unit  # noqa: E402
from occupancy.reconcile import reconcile  # noqa: E402


def load_facts(path: str):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    units = [Unit(u["id"], u["kind"], u["capacity"]) for u in data["units"]]
    leases = [Lease(l["id"], l["unit_id"], l["seats"],
                    date.fromisoformat(l["start"]), date.fromisoformat(l["end"]))
              for l in data["leases"]]
    maint = [Maintenance(m["unit_id"], date.fromisoformat(m["start"]), date.fromisoformat(m["end"]))
             for m in data.get("maintenance", [])]
    return units, leases, maint


def load_dashboard(path: str) -> dict[date, float]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {date.fromisoformat(k): float(v) for k, v in data["daily_rates"].items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="sample_data.json")
    ap.add_argument("--dashboard", default="dashboard_2026-11.json")
    ap.add_argument("--month", default="2026-11")
    ap.add_argument("--log", default="logs/reconcile.log")
    args = ap.parse_args()

    y, m = (int(x) for x in args.month.split("-"))
    units, leases, maint = load_facts(args.data)
    result = reconcile(units, leases, maint, date(y, m, 1), load_dashboard(args.dashboard),
                       log_path=args.log)

    s = result["summary"]
    print("%s 已租 %d / 可租 %d 座位日，出租率 %.4f%%，核对 %d 天，差异 %d 天"
          % (result["month"], s["occupied_seat_days"], s["available_seat_days"],
             s["rate"] * 100, s["checked_days"], s["mismatch_days"]))
    for d in result["details"]:
        print("  差异 %s：口径 %.6f，驾驶舱 %.6f，差 %.4f 个百分点（可租 %d / 已租 %d，租约 %s）"
              % (d["stat_date"], d["expected_rate"], d["actual_rate"], d["diff_pp"],
                 d["available_seat_days"], d["occupied_seat_days"], ",".join(d["lease_ids"])))
    print("日志已写入 %s" % args.log)
    return 1 if result["details"] else 0


if __name__ == "__main__":
    sys.exit(main())
