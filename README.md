# 出租率口径单元测试与对账脚本 · #3240

对应工单 **S2-SPACE-015**。范围：出租率口径的单元测试、按日对账脚本、运行说明。
驾驶舱本身（S3-DASH）不在本单内 —— 对账脚本按"驾驶舱返回的按日出租率"这个契约工作，用快照文件代替接口。

## 1. 目录

```
occupancy/models.py       Unit / Lease / Maintenance，左闭右开区间，月内日期枚举
occupancy/calc.py         口径（纯函数）：按日 available/occupied，按月累计
occupancy/reconcile.py    对账：逐日比对，>0.1pp 输出明细，可写日志
run_reconcile.py          每月初的入口，退出码 0/1 便于 cron 告警
sample_data.json          虚构的一个月租约数据（覆盖 5 类边界）
dashboard_2026-11.json    驾驶舱快照（11-12 人为偏 0.5pp，用于演示发现能力）
tests/test_acceptance.py  6 类边界 + 对账明细 + 运行说明校验
```

## 2. 口径（写死在代码注释里，避免每次对账重新解释）

**出租率 = Σ已租座位日 / Σ可租座位日**，按月累计。

| 情形 | 处理 | 为什么 |
|---|---|---|
| 月中起租 | 从起租日当天开始计入 | 区间左闭 |
| 月中退租 | 退租日当天**不**计入 | 区间右开，下一位当天可起租 |
| 维修工位 | 从**可租**里扣（分母 −1） | 业务口径：修的时候不算可售 |
| 共享空间 | 按**座位容量**折算（占 4 座 = 4） | 不是"占用 1 个空间" |
| 续约无缝 | 前后租约在同一天衔接，不空档不双计 | 左闭右开天然成立 |
| 月度值 | 累计相除，**不是**日均出租率的算术平均 | 分母变化时两者不等价 |

## 3. 运行说明（定时执行方式）

每月初 02:00 对上一个自然月做对账，写入 `logs/reconcile.log`，出现差异时以非 0 退出码触发告警：

```cron
# 每月 1 日 02:00 对账上月（crontab -e）
0 2 1 * * cd /opt/space/reconcile && /usr/bin/python3 run_reconcile.py \
    --data sample_data.json --dashboard dashboard_previous.json \
    --month "$(date -d 'last month' +\%Y-\%m)" --log logs/reconcile.log \
    >> logs/cron.out 2>&1
```

手动跑当月：

```bash
python run_reconcile.py --data sample_data.json --dashboard dashboard_2026-11.json \
    --month 2026-11 --log logs/reconcile.log
# 预期输出：
# 2026-11 已租 100 / 可租 357 座位日，出租率 28.0112%，核对 30 天，差异 1 天
#   差异 2026-11-12：口径 0.500000，驾驶舱 0.505000，差 0.5000 个百分点（可租 12 / 已租 6，租约 L1,L2,L3）
# 退出码 1
```

日志每行一条 JSON（`{"kind":"reconcile", ...}`），便于月度复盘时用 `jq` 汇总：

```bash
jq -s 'map(.summary) | map({month, rate, mismatch_days})' logs/reconcile.log
```

## 4. 测试

```bash
python -m unittest discover -s tests -t . -v      # 11 passed，零第三方依赖
```

## 5. 验收对照

| # | 验收原文 | 用例 | 实测 |
|---|---|---|---|
| 1 | 边界情况不少于 5 种，测试全部通过 | `test_ac1_*`（6 个） | 月中起租、月中退租、维修扣分母、共享空间按座位、续约无缝、月末+累计，每种都有手算期望；月度基线 100/357 = 28.0112% |
| 2 | 对账脚本能发现人为制造的差异并输出明细（测试通过） | `test_ac2_detects_manufactured_diff_with_detail`、`test_ac2_threshold_boundary_not_reported`、`test_ac2_identical_values_report_nothing`、`test_ac2_writes_log_line` | 11-12 篡改 0.5pp → 明细含日期/口径值/驾驶舱值/差值/分子分母/租约 id；恰好 0.1pp 不报、0.11pp 报；日志落一行 JSON |
| 3 | 运行说明写明定时执行方式 | `test_ac3_readme_documents_cron` | 本文第 3 节含 `0 2 1 * *` 与 `run_reconcile.py`，测试直接校验这两处 |

## 6. 边界与取舍

- **阈值判定写成 `round(abs(diff)*100, 6) > 0.1`**：恰好 0.1pp 不报，测试里有这条边界，避免"0.1 算不算超"的口头争议。
  这里踩过一个真实的浮点坑：`0.5 - 0.501` 在二进制浮点里是 `0.10000000000000005`，不四舍五入会把"恰好 0.1"误报成超标。
- **按日明细必须带分子分母**：只给"差 0.5pp"没用，运营要知道是"多算了一间"还是"漏了维修"，所以明细带 `available/occupied/lease_ids`。
- **不查库**：事实数据从 JSON 读，驾驶舱从快照读。接真实系统时只替换两个 loader，口径与对账逻辑不动。
- **退出码承担告警职责**：cron 里不解析 stdout，非 0 即告警。

## 7. 不在本单范围

驾驶舱接口实现与图表（S3-DASH）、租约写入与退租流程（S2-SPACE）、工位维修工单、前端页面。
