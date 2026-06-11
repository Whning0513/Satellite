# M5 Real Repair Audit

## Status

**LUNAR RETURN INVALIDATED.** The M5 lunar trajectory does not reach Earth.

## Status Summary

| 项目 | 结果 |
|---|---|
| Direct Lambert baseline | ✅ 执行；88 候选，0 fair |
| DSM baseline (this repair) | ✅ 执行；923 候选（去重后），203 strict fair，324 near-feasible |
| DSM fixed-date (t0=61066) | ✅ 18 strict fair at same launch date |
| Lunar budget (return event check) | ❌ **INVALID** — lunar return event missing; trajectory ends at perihelion |
| Formal saving ratio | ❌ **INVALIDATED** — lunar has no Earth return, cannot compare |
| M5 status | **lunar_return_event_missing** |

## 修正历史

| 阶段 | 状态 | 原因 |
|------|------|------|
| 旧 −224.7% | 跨日期比较无效 | DSM t0=61125 vs lunar t0=61066 |
| 旧 −187.3% | **INVALIDATED** | lunar return_vinf 是在近日点（0.28 AU, 164 M km 外）测得的速度差，不是地球再入速度 |
| 当前 | lunar_return_event_missing | M5 lunar trajectory 未完成 Earth return |
| pure lunar free return 不存在 | — | 即使延长传播到全周期，closest approach 9.15 M km，仍远未到地球 |

## DSM no-lunar baseline（独立有效）

- **状态：ACTUAL_RESULT** — Lambert 正确到达地球位置（r≈1.0 AU）
- **Best fixed-date (t0=61066):** total_dv_proxy = 25.41 km/s, return_vinf = 5.97 km/s
- **不能与 incomplete lunar trajectory 做 saving ratio 比较**

## M5 lunar+return-DSM completion（另建任务类）

天阳近日点+45 天增加返回 Lambert 后，可完成返回：

| Quantity | Value |
|----------|------|
| Return DSM | 26.75 km/s |
| Arrival return_vinf | 6.18 km/s |
| Completed total_dv_proxy | 36.87 km/s |
| Reference ratio vs DSM no-lunar | −45.1% |
| Classification | DIAGNOSTIC — separate mission class, not pure lunar |

## 与之前对比

| 指标 | 之前（−187.3%） | 当前 |
|---|---|---|
| DSM candidates | 923 | 923 |
| Strict fair | 203 | 203 |
| Lunar Earth return | 假阳性（77.88 误认为再入速度） | **不存在** |
| Formal saving ratio | −187.3%（INVALIDATED） | **None** |
| Status | comparison-complete-negative-saving | **lunar_return_event_missing** |
