# M5 Real Repair Audit (Corrected)

## Status Summary

| 项目 | 结果 |
|---|---|
| Direct Lambert baseline | ✅ 执行；88 候选，0 fair |
| DSM baseline (this repair) | ✅ **执行；923 候选（去重后），203 strict fair，324 near-feasible** |
| Fixed-date DSM candidates (t0=61066) | ✅ **18 strict fair at same launch date as lunar** |
| Lunar budget (same proxy) | ✅ 执行；total = 73.00 km/s |
| Formal fixed-date saving ratio | ✅ **−1.8733 (−187.3%)** |
| Invalid cross-date ratio (t0=61125) | 保留但注明 invalid; 值 = −2.2472 (−224.7%) |
| M5 status | **comparison-complete-negative-saving** |

**修正说明**：之前报告的 −224.7% 是跨日期比较（DSM t0=61125 vs lunar t0=61066），不能作为 M5 fixed-date ratio。修正后的正式 fixed-date ratio 为 −187.3%（发射日期相同，t0=61066）。

---

## Budget sensitivity

| Mode | Lunar total | No-lunar total | Saving ratio | Lunar saves Δv? |
|------|-----------:|---------------:|------------:|:--------------:|
| A: threshold braking | 73.00 km/s | 25.41 km/s | **−187.3%** | No |
| B: full return braking | 88.00 km/s | 31.38 km/s | **−180.5%** | No |
| C: entry speed proxy | 73.80 km/s | 25.41 km/s | **−190.5%** | No |

**所有三种 budget mode 均为负。结论稳健：当前月球借力方案在统一代理口径下不节能。**

---

## 结果说明

**DSM 搜索策略**：发射后沿 patched-conic r_p=0.3 AU 椭圆轨道运行，解 Kepler 方程得到轨道上任一点 (r, v)，在该点实施 DSM，然后 Lambert 从该点转移到地球返回。搜索了 23 个发射日期 x 29 个 tof1 x 18 个 tof2 x 3 个 Lambert 分支，共 ~36K 组合，运行约 3s。

**Budget 口径统一**（双方使用一致公式）：
```
total_dv_proxy = departure_vinf + residual + max(0, return_vinf − 15)
```

**Fixed-date (t0=61066) comparison**：

| 分量 | Lunar | DSM no-lunar |
|------|-------|--------------|
| departure_vinf | 10.12 km/s | 10.01 km/s |
| dsm / lunar_residual | 0.00 km/s | 15.40 km/s |
| return_vinf | 77.88 km/s | 5.97 km/s |
| return_braking | 62.88 km/s | 0.00 km/s |
| **total_dv_proxy** | **73.00 km/s** | **25.41 km/s** |
| **saving ratio** | — | **−187.3%** |

**负值的物理原因**：月球借力出仓 v_inf（10.12 vs 10.01 km/s）仅有 0.11 km/s 差异，但返回速度差异巨大（77.88 vs 5.97 km/s）。在 `max(0, return_vinf − 15)` 这个代理下，月球方案需要 62.88 km/s 的制动代理，而 DSM 方案为 0。DSM 方案的 15.40 km/s 深空机动代价远小于月球方案的返回制动代价。

## 对 M5 评分的影响

- M5.4（与无月借对比）：**完成** — 同一发射日期下有 18 个 strict fair DSM no-lunar 候选
- M5.5（节能比例）：**完成** — formal fixed-date saving ratio = −187.3%（负值表示不节能）
- **M5 状态不是 "success" 而是 "comparison-complete-negative-saving"**

## 与之前审计对比

| 指标 | 之前 (c32579a) | 现在 (修正后) |
|---|---|---|
| DSM candidates | 2 | 923 (97 at lunar t0) |
| Strict fair | 0 | 203 (18 at lunar t0) |
| Formal fixed-date ratio | None | −1.8733 |
| Cross-date ratio | None | −2.2472 (invalid) |
| Status | partial | comparison-complete-negative-saving |
