"""三条验收标准：口径边界（≥5 种）、对账明细、运行说明中的定时方式。

所有期望值都是手算的：先算「Σ已租座位日 / Σ可租座位日」，再反过来验每天的分子分母。
"""
from __future__ import annotations

import re
import unittest
from datetime import date
from pathlib import Path

from occupancy.calc import daily, monthly
from occupancy.models import Lease, Maintenance, Unit
from occupancy.reconcile import reconcile

ROOT = Path(__file__).resolve().parent.parent
MONTH = date(2026, 11, 1)


def fixture():
    """A/B 为独立工位（容量 1），C 为共享空间（容量 10）。"""
    units = [Unit("A", "desk", 1), Unit("B", "desk", 1), Unit("C", "shared", 10)]
    leases = [
        Lease("L1", "A", 1, date(2026, 11, 1), date(2026, 11, 16)),    # 前半月
        Lease("L4", "A", 1, date(2026, 11, 16), date(2026, 12, 1)),    # 续约，无缝
        Lease("L2", "B", 1, date(2026, 11, 11), date(2026, 11, 21)),   # 月中起租 + 月中退租
        Lease("L3", "C", 4, date(2026, 11, 1), date(2026, 11, 16)),    # 共享空间 4/10
    ]
    maintenance = [Maintenance("B", date(2026, 11, 5), date(2026, 11, 8))]  # 3 天维修
    return units, leases, maintenance


def day_row(day: date):
    units, leases, maint = fixture()
    rows = {r.day: r for r in daily(units, leases, maint, MONTH)}
    return rows[day]


class AC1BoundaryCases(unittest.TestCase):
    """AC-1：边界不少于 5 种 —— 这里覆盖 6 种，每种都有手算期望。"""

    def test_ac1_mid_month_start(self):
        """边界 1：月中起租。11-10 无 B，11-11 起计入。"""
        self.assertEqual(day_row(date(2026, 11, 10)).occupied, 5)   # A1 + C4
        self.assertEqual(day_row(date(2026, 11, 11)).occupied, 6)   # + B1
        self.assertEqual(day_row(date(2026, 11, 11)).lease_ids, ["L1", "L2", "L3"])

    def test_ac1_mid_month_end(self):
        """边界 2：月中退租。左闭右开，11-15 计、11-16 不计。"""
        self.assertIn("L3", day_row(date(2026, 11, 15)).lease_ids)
        self.assertNotIn("L3", day_row(date(2026, 11, 16)).lease_ids)

    def test_ac1_maintenance_reduces_available(self):
        """边界 3：维修工位从可租里扣（分母 -1），不是从已租里扣。"""
        self.assertEqual(day_row(date(2026, 11, 4)).available, 12)
        self.assertEqual(day_row(date(2026, 11, 5)).available, 11)
        self.assertEqual(day_row(date(2026, 11, 7)).available, 11)
        self.assertEqual(day_row(date(2026, 11, 8)).available, 12)

    def test_ac1_shared_space_counts_seats(self):
        """边界 4：共享空间按座位折算（4 个座位就是 4），不是"占用 1 个空间"。"""
        row = day_row(date(2026, 11, 1))
        self.assertEqual(row.occupied, 5)       # A1 + C4
        self.assertEqual(row.available, 12)     # A1 + B1 + C10

    def test_ac1_renewal_is_seamless(self):
        """边界 5：续约无缝 —— 前后两份租约不得出现空档或双计。"""
        before = day_row(date(2026, 11, 15)).lease_ids
        after = day_row(date(2026, 11, 16)).lease_ids
        self.assertEqual(before.count("L1"), 1)
        self.assertNotIn("L4", before)
        self.assertEqual(after.count("L4"), 1)
        self.assertNotIn("L1", after)
        self.assertEqual(day_row(date(2026, 11, 16)).occupied, 2)   # A(L4) + B

    def test_ac1_month_end_and_totals(self):
        """边界 6：月末 + 月度累计。100 / 357 为手算基线。"""
        self.assertEqual(day_row(date(2026, 11, 30)).occupied, 1)
        units, leases, maint = fixture()
        summary = monthly(daily(units, leases, maint, MONTH))
        self.assertEqual(summary["occupied_seat_days"], 100)
        self.assertEqual(summary["available_seat_days"], 357)   # 12×30 − 1×3
        self.assertAlmostEqual(summary["rate"], 100 / 357, places=9)


class AC2ReconcileDetail(unittest.TestCase):
    def _baseline(self) -> dict[date, float]:
        units, leases, maint = fixture()
        return {r.day: r.rate for r in daily(units, leases, maint, MONTH)}

    def test_ac2_detects_manufactured_diff_with_detail(self):
        units, leases, maint = fixture()
        rates = self._baseline()
        rates[date(2026, 11, 12)] = 0.505          # 真值 0.5 → 差 0.5pp
        result = reconcile(units, leases, maint, MONTH, rates)

        self.assertEqual(result["summary"]["mismatch_days"], 1)
        detail = result["details"][0]
        self.assertEqual(detail["stat_date"], "2026-11-12")
        self.assertAlmostEqual(detail["expected_rate"], 0.5, places=6)
        self.assertAlmostEqual(detail["actual_rate"], 0.505, places=6)
        self.assertAlmostEqual(detail["diff_pp"], 0.5, places=4)
        self.assertEqual(detail["available_seat_days"], 12)
        self.assertEqual(detail["occupied_seat_days"], 6)
        self.assertEqual(detail["lease_ids"], ["L1", "L2", "L3"])

    def test_ac2_threshold_boundary_not_reported(self):
        """恰好 0.1pp 不报；0.11pp 才报（判定式是 > 0.1）。"""
        units, leases, maint = fixture()
        rates = self._baseline()
        rates[date(2026, 11, 13)] = 0.501         # 0.1pp
        rates[date(2026, 11, 14)] = 0.5011        # 0.11pp
        result = reconcile(units, leases, maint, MONTH, rates)
        self.assertEqual([d["stat_date"] for d in result["details"]], ["2026-11-14"])

    def test_ac2_identical_values_report_nothing(self):
        units, leases, maint = fixture()
        result = reconcile(units, leases, maint, MONTH, self._baseline())
        self.assertEqual(result["summary"]["mismatch_days"], 0)
        self.assertEqual(result["summary"]["checked_days"], 30)

    def test_ac2_writes_log_line(self):
        import tempfile
        units, leases, maint = fixture()
        rates = self._baseline()
        rates[date(2026, 11, 12)] = 0.505
        path = Path(tempfile.mkdtemp()) / "reconcile.log"
        reconcile(units, leases, maint, MONTH, rates, log_path=path)
        text = path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(text), 1)
        self.assertIn('"mismatch_days": 1', text[0])


class AC3RunbookHasSchedule(unittest.TestCase):
    def test_ac3_readme_documents_cron(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"0\s+2\s+1\s+\*\s+\*", "运行说明必须写明每月初的定时表达式")
        self.assertIn("run_reconcile.py", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
