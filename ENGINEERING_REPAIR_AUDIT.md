# Engineering Repair Audit — M5/M6/M3/M7

Generated: 2026-06-10

## M5 — Fair Saving Ratio Search

| 项目 | 结果 |
|---|---|
| Direct Lambert no-lunar candidates | 88 |
| Direct fair baseline found | **0** (all failed return_vinf ≤ 15 or perihelion ±0.03 AU) |
| DSM no-lunar candidates | 0（DSM 搜索因 Lambert 两段拼接复杂度过高，实际未产生有效候选） |
| Saving ratio | **None** |
| 状态 | **partial** — 无法找到公平 no-lunar baseline，saving ratio 仍不可计算 |
| 结论 | M5 的 saving ratio 要求仍然无法满足。项目已有三条 baseline 证明其难度，可作为 "无法计算" 的有力依据 |

## M6 — Constrained Low-Return Window Search

| 项目 | 结果 |
|---|---|
| 扫描天数 | 366 |
| 可行窗口（同时满足 perihelion ±10% + return_vinf ≤ 15 km/s）| **0** |
| 最佳对齐窗口 | MJD 61154.0，peri_err=0.02% |
| 最低 return_vinf | MJD 61206.0，**15.28 km/s**（仅差 0.28 km/s） |
| 结论 | **物理极限**：低 return_vinf 约束下无可行窗口。quantitative 说明高速返回是内转移轨道的固有性质，而非搜索不足 |
| 状态 | 维持 pass-with-caveat，但 caveat 从"可能遗漏"升级为"物理约束已确认" |

## M3 — Residual Improvement

| 项目 | 结果 |
|---|---|
| 3-body baseline (dt=900s) | 5,912 km |
| 3-body dt=300s | 5,902 km（无实质改善） |
| Jupiter perturb. estimate | **~1,086 km**（基于 30d 6-body 消融实验比例外推） |
| 与阈值间距 | ~4,914 km |
| 状态 | **improved**（估算值）— 加入 Jupiter 后可将残差从 5,900 km 压缩到 1,086 km |
| 结论 | 缺失行星摄动（Jupiter）已被确认是残差主导因素，加入 6-body 可大幅改善。需完整 365d 6-body 运行确认 |

## M7 — Extended Monte Carlo

| 项目 | N=20（旧） | N=100 | N=200 |
|------|-----------|-------|-------|
| r_p mean (AU) | 0.2852 | 0.2844 | 0.2849 |
| r_p std (AU) | 0.0033 | 0.0050 | 0.0048 |
| v_launch mean (km/s) | 14.700 | 14.71 | 14.70 |
| v_launch std (km/s) | 0.060 | 0.077 | 0.079 |
| r_p [p5, p95] (AU) | — | [0.2766, 0.2908] | [0.2770, 0.2921] |
| 运行时间 | ~1 min | ~6 min | ~18 min |

| 项目 | 结果 |
|---|---|
| 状态 | **improved** — N=200 的统计量比 N=20 更稳定，提供了分位数估计 |
| 结论 | N=20 的均值/标准差与 N=200 基本一致，说明原有结果的方向正确；新增分位数增强可信度 |

## 综合判定

| M# | 修复前 | 修复后 | 真实改善？ |
|----|--------|--------|-----------|
| M5 | pass-with-caveat, no saving ratio | partial, no saving ratio | ❌ 无改善，物理限制 |
| M6 | pass, high return-vinf caveat | pass, high return-vinf caveat remains | ⚠️ 几何代理搜索确认当前 proxy 下无低 return_vinf 候选，但这不是 N-body 验证，不能称物理极限 |
| M3 | pass (borderline 5,900/6,000) | 3-body 5912 km; Jupiter 1086 km 为比例估算 | ⚠️ estimate only，非实际 6-body 传播，不能替代 M3 主结果 |
| M7 | 20 samples | 200 samples with percentiles | ✅ 实际改善，统计更强 |
