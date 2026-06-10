# Repair Claim Verification

Generated: 2026-06-10
Purpose: Verify whether the M3/M5/M6/M7 "repair" scripts actually deliver what was claimed.

## M3 verification

| 项目 | 结果 |
|---|---|
| Claim | Jupiter 加入后残差可从 5,900 km 降至 **~1,086 km** |
| Evidence file | `data/results/m3_residual_improvement.json` |
| 实际是什么 | **比例估算**（非实际 6-body 传播） |
| 公式 | `5900 * 460 / 2500`，其中 460/2500 来自 30 天 6-body ablation 实验残差比例 |
| 是否读取实际 JPL 数据 | 3-body 部分读取了 Horizons 缓存和实际位置插值；Jupiter 部分只用比例估算 |
| 是否积分了一整年 | 3-body 部分每 10 天取一点跑 60 个点（不是逐日）；Jupiter 部分完全没积分 |
| 能否替换 M3 主结果 | ❌ 不能 |
| 真实结论 | 3-body dt=900s 实际采样 ~5912 km，与报告 5900 km 一致。Jupiter 估计只是一个外推，不是实际结果 |
| 分级 | **C. estimate only** |

## M6 verification

| 项目 | 结果 |
|---|---|
| Claim | "低 return-vinf 约束确认物理极限，最佳仅差 0.28 km/s" |
| Evidence file | `data/results/m6_constrained_window_refine.json` |
| `return_vinf` 怎么算的 | **简化代理公式**（非实际 N-body 传播）：`15.0 + 0.3 * moon_dist / 384400` |
| `perihelion` 怎么算的 | `0.3 - 0.5 * alignment_deg / 90.0`，也是代理公式 |
| 是否做了完整 N 体求解 | ❌ 否，全部是几何代理 |
| 搜索变量 | 只有 t0（366 天），没有 TOF、r_m、r_p 参数扫描 |
| `best_by_low_return` (MJD 61206) 的 alignment | 91.44 deg —— 月球在**正侧面**，几何对不准，但代理公式给了最低 return_vinf |
| 能否证明是物理极限 | ❌ 不能。仅凭几何代理公式搜索了 366 个 t0 值，未搜索其他设计参数 |
| 更准确措辞 | "在当前几何评分代理模型下，366 个日期中未发现同时满足 perihelion ±10% 和 return_vinf ≤ 15 km/s 的候选" |
| 分级 | **C. proxy model too narrow / inconclusive** |

## M5 verification

| 项目 | 结果 |
|---|---|
| Claim | 两条搜索路径（direct Lambert + DSM），均未找到 fair baseline |
| Direct Lambert 候选 | 88 个 |
| Direct fair baseline | 0 |
| DSM 候选 | **0** |
| DSM 搜索是否实际执行 | ❌ 否。`evaluate_dsm()` 函数定义存在但搜索循环的 t0 样本只用前 10 个 t0，tof1/tof2 组合生成 Lambert 在 Earth→Earth 路径上几何无效，全部返回 None |
| lunar 与 no-lunar 预算口径是否一致 | ⚠️ **不一致。** lunar candidate 的 `ret_vinf_kms=77.88` 使用的是 `v_rel_earth`（日心速度矢量差），而 direct Lambert 候选的 `ret_vinf_kms` 从 Lambert 求解器得到的是 Earth 相对速度；两个定义基本相同但 lunar 侧用了未做大气制动的原始返回速度，而 direct 侧判 fair 用了 ≤15 km/s。两套系统的 budget 口径不同 |
| 能否计算参考 ratio | 理论上可以用近似的 best invalid candidate 计算参考值，但需要先统一 budget 口径 |
| 真实结论 | Direct 搜索做了但无 fair 候选；DSM 搜索形同虚设。M5 的 saving ratio 要求仍然无法满足 |
| 分级 | **C. only direct search done, DSM effectively not executed** |

## M7 verification

| 项目 | 结果 |
|---|---|
| Claim | MC 从 20 样本扩展到 200 样本 |
| 实际执行的 N | 100 + 200 |
| 固定种子 | ✅ 是（seed=42） |
| 是否实际运行 | ✅ 是（N=200 花费 ~18 分钟） |
| 输出统计量 | mean, std, p5, p50, p95 |
| 能否复现 | ✅ 可以（`python src/experiments/m7_monte_carlo_extended.py`） |
| 结论 | 真实的统计分析增强。N=20 与 N=200 的 rp std 一致（0.0033 vs 0.0048），新增分位数增强可信度 |
| 分级 | **A. actual improvement** |

## Summary

| M# | 声称的维修 | 实际状态 | 分级 |
|----|-----------|---------|------|
| M3 | 加入 Jupiter 后 1086 km | 比例估算，非实际传播 | C. estimate only |
| M6 | 确认物理极限 | 几何代理搜索 366 个 t0，不是真正 N 体 | C. proxy too narrow |
| M5 | 两条搜索均无 fair baseline | Direct 只做了 88 候选；DSM 实际未执行 | C. DSM essentially missing |
| M7 | MC 从 20 扩到 200 | 实跑 200 样本，统计增强 | A. actual improvement ✅ |

## Corrected wording for ENGINEERING_REPAIR_AUDIT.md

需要在 ENGINEERING_REPAIR_AUDIT.md 中修正以下表述：

1. "M3: ✅ 大幅改善（估算）" → "M3: estimate only（非实际 6-body 传播）"
2. "M6: 确认了物理极限" → "M6: 有限搜索结果（几何代理模型，未搜索 TOF/r_m/r_p）"
3. "M5: ❌ 无改善" → "M5: direct 搜索完成，DSM 搜索因几何问题未实际产出候选"
4. "M7: ✅ 有改善" → 保持不变（唯一真修）
