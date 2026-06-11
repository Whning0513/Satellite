# External Benchmark Comparison

## 核心发现

**M5 lunar trajectory "return_vinf" = 77.88 km/s 不是地球再入速度，是飞船在近日点（0.2877 AU）与 1.64 亿公里外地球的日心速度差。** 该导航传播在半个周期（近日点）停止，并未返回地球位置。而 DSM no-lunar 的 Lambert 解算直达地球位置（~1 AU）。这两个量的比较毫无意义，M5 fixed-date saving ratio 被全面否决。

## Summary

| Topic | external benchmark | project value | status | action |
|---:|---:|---:|:---|:---|
| A patched-conic Δv | r_p=0.2: v_launch≈16.84, 0.3: ≈14.71; total 2×v_launch ≈29.4 | 16.8363 / 14.7036 / 29.41 | PASS | 澄清 29.41=2×v_launch 不是 2×heliocentric impulse |
| B return_vinf sanity | bound-orbit 上限≈71.9 km/s | lunar 77.88 **但不在地球** | **RED** | 轨迹在近日点停止，非地球再入速度 |
| C lunar saving ratio | 负 ratio 可成立但继承 B 的风险 | −187.3% (fixed-date) | **RED** | 仅在近日点 vs 地球，口径完全不同 |
| D Horizons residual | 趋势合理 but same-source caveat | 5912→1401→126 | PASS_WITH_CAVEAT | 126 km 标注 same-source, 不是独立验证 |
| E Velocity-Verlet | VV O(Δt²), dt=900s 合理 | pos_err 8.27e-5, energy drift <5e-15 | PASS | 保留现有 caveat |
| F Swingby angle | median 0.026° | median 0.026°, max 3.75° | PASS_WITH_CAVEAT | max 3.75° 需标注对应 case |
| G DSM 15.40 km/s | 数学 baseline 可行 | 15.40 km/s | WARN | 必须标注数学 baseline 非工程可行 |
| H M6 search | target fn 没惩罚 return_vinf | top 10 return_vinf 53–81 | **RED** | 排序函数只含对准角+距离，无 return_vinf 项 |
| I O3+ corrector | position-shooting 合理 | final miss 66,210km, vel residual 22km/s | PASS_WITH_CAVEAT | 必须标注 not rendezvous |
| J O4+ Venus | 17.45 km/s powered 不可行 | 0 feasible | PASS_WITH_CAVEAT | 标签为 infeasible diagnostic |

## Red flags

1. **B/C：M5 lunar trajectory 传播不全** — S5 只走到近日点（~0.28 AU），没走到地球。v_rel_earth = 77.88 km/s 是两个不同位置物体的速度差，不是地球遭遇速度。**M5 fixed-date saving ratio (−187.3%) 全面作废。**
2. **H：M6 排序函数无 return_vinf 惩罚** — 几何评分只对准角+月距，完全不管返回速度。top 10 全部 return_vinf > 53 km/s 不能说明物理必然，只能说明目标设计缺陷。

## Fixes performed

| Fix | File | Status |
|-----|------|--------|
| return_vinf 能量/帧审计 | `return_vinf_frame_energy_audit.py` | ✅ 确认所有非 DSM case 的 return_vinf 是近日点速度差而非真实再入速度 |
| M3 泄漏审计 | `m3_horizons_leakage_audit.py` | ✅ 无数据泄漏；126 km 是 same-source IC propagation check |
| 标签修正 | 审计文档 | 需要更新 |
| 口径澄清 | 文档 | 需要更新 |

## Remaining risks

1. **M5/M6 核心结论失效**：M5 lunar 轨迹不返回到地球，所有基于 77.88 km/s 的 budget、saving ratio、sensitivity 分析全部无效。这不是坐标系/单位/数值 bug，是传播时长设计问题。
2. **M6 排序函数需要加 return_vinf 惩罚**当前 top 结果不反映低返回速度约束。
3. **M3 126 km 是 same-source**，但不是泄漏，需要标注。
4. **DSM no-lunar baseline 仍有效**，但其作为 "M5 no-lunar comparison" 的对手（lunar trajectory）无效。
