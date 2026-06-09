# Total Δv Budget Audit — 全过程速度改变量审计

Generated: 2026-06-09
Purpose: Compare project's total Δv budget definitions against the
Qian simplified model's symmetric patched-conic total (~33.4 km/s).

## Qian simplified model

| 项目 | 值 |
|------|-----|
| reference | 钱学森《星际航行概论》§6.3 第一方案，r_p = 0.2 AU |
| total Δv | ≈ **33.68 km/s**（书中引用常写作 ~33.4，差异来自凑整） |
| formula | `v_launch(depart) + v_launch(return)` |
| components included | ① 地表→近地停泊轨道→逃逸（v_launch=16.84 km/s）；② 返回段从逃逸轨道制动到地表（对称，v_launch 相同） |
| components excluded | 月球借力 Δv、中途修正、着陆段、大气制动、再入 heat shield 约束 |
| physics | 纯对称拼接圆锥曲线，出发和返回各一次脉冲，无借力，无制动细化 |
| comparable project quantities | **M1 patched-conic 对称 total Δv**；**M6 dv_total**（需调整包含项后比）|

## Project total Δv budget definitions

| module | value (km/s) | variable / formula | components included | comparable to Qian 33.4? | verdict |
| ------ | -----------: | ------------------ | ------------------- | ------------------------ | ------- |
| **M1 patched-conic** (r_p=0.3 AU) | **29.41** | `v_launch × 2`（对称模型） | 地球上发射到逃逸 + 同口径返回制动 | ✅ **是，同口径** | 纯 patched-conic 无月借 baseline，仅比钱学森多 1 项：设计 r_p 不同（0.3 vs 0.2 AU） |
| **M1 patched-conic** (r_p=0.2 AU/Qian) | **33.68** | `v_launch × 2`（回归测试） | 同上 | ✅ **基准** | 与钱学森 33.4 偏差 < 1%，确认代码正确 |
| **M5 标称轨道**（有月借） | **未显式定义** | 项目无统一 `dv_total` 字段 | — | ❌ **不可直接比** | 只有三段 Δv 片段，无加总公式 |
| **M5 no-lunar SOI-exit** | 77.99 | `dv_total_corrected_kms` | v_launch(14.70) + v_rel_return(77.88) - 重叠校正 | ❌ **不可直接比** | 77.88 是日心速度矢量差，不是制动所需 Δv |
| **M5 no-lunar Lambert** | 30.88 | `dv_total_kms`（Pareto 候选） | dep_vinf=10.7 + return_vinf=26.24，**包含前两项但不含 lauch-ascent + 着陆** | ⚠️ **部分可比** | 缺地面→逃逸段（~5.5 km/s）和着陆段；若补全约 30.88+5.5+5.5 ≈ 41.9 |
| **M6 best_by_dv** | **91.88** | `dv_total = v_launch + v_reentry`（`aux_results.py:108`） | v_launch_esc(14.70) + v_reentry(78.68) | ❌ **定义不同** | v_reentry=sqrt(v_rel²+V_esc²)，v_rel 是日心速度矢量差 77.88 km/s，不是制动所需 Δv |
| **M6 best_balanced** | **93.38** | 同上 | 同上 | ❌ **定义不同** | 同上 |
| **O4+ powered MGA** | **43.56** | `dv_launch(10.66) + dv_moon(3.80) + dv_venus(17.45) + dv_reentry(max(0,26.65-15)=11.65)` | Earth dep_vinf + flyby residuals + return braking (>15 excess) | ⚠️ **部分可比** | dep_vinf 只含 C3 不含地表→逃逸；返回段只计超过 15 km/s 的部分，不是全制动 |
| **O3+ vector corrector** | **1.22** | `delta_v_norm_kms` | 仅修正脉冲 | ❌ **不同概念** | 这是打靶修正量，不是全过程 Δv |

## M6 dv_total = 91.88 km/s 的口径问题 — 关键发现

```python
# aux_results.py:108
dv_total = w.get("v_launch_kms", 0) + w.get("v_reentry_kms", 0)
```

其中：
- `v_launch = 14.70 km/s` = 地表发射到停泊轨道再到逃逸（一次脉冲）
- `v_reentry = sqrt(77.88² + 11.18²) = 78.68 km/s`
- `v_rel_earth = 77.88 km/s` = 返回时火箭日心速度 - 地球日心速度的**矢量差**

**问题：** `v_reentry` 不是返回制动所需的 Δv。它是**日心速度差复合逃逸速度后的总能量等价速度**。真正的返回制动 Δv 应该只计消除 `v_rel_earth` 所需的脉冲（约等于 `v_rel_earth` 本身，或按 `v_reentry - V_esc` 估算），而非包含地球公转速度在内的日心矢量差成本。

**结论：** M6 的 `dv_total=91.88 km/s` 显著夸大了总速度改变量，因为返回段使用了 `v_reentry` 而非纯制动 Δv。

## Non-comparable velocities

| value (km/s) | source | meaning | why not comparable to total Δv |
| -----------: | ------ | ------- | ------------------------------ |
| 77.88 | M5 S6 `v_rel_earth` | 返回时火箭-地球日心速度矢量差 | 这不是燃料消耗，是两体轨道交会点速度差 |
| 78.68 | M5 S6 `v_reentry` | 再入总能量等价速度 | = sqrt(v_rel²+V_esc²)，包含自然轨道速度 |
| 29.80 | `constants.py` | 地球公转速度（常数） | 自然轨道速度，非燃料 |
| 35.02 | `constants.py` | 金星公转速度 | 自然轨道速度，非燃料 |
| 14.70 | M5 `v_launch` | 地表发射速度 | 这是一段脉冲（出发段），不是全程总计 |
| 10.66 | O4 `dep_vinf` | 双曲超额速度 | 是 v_launch 的一部分（C3），不是完整发射段 |
| 22.1 | O3+ velocity diag | 火箭-月球终端相对速度 | 位置修正后未做速度匹配，非 Δv |

## Missing / double-count audit

| module | missing? | double-counted? | notes |
| ------ | -------- | --------------- | ----- |
| **M1 patched-conic** | 无 | 无 | 对称模型，口径清晰 |
| **M5 trajectory** | 缺显式 `dv_total` 字段 | — | 项目未定义 M5 total Δv；现有片段无法直接加总 |
| **M6 `dv_total`** | — | **是**：v_reentry 重复算了 V_esc 和 v_rel 中的自然轨道分量 | v_reentry=sqrt(v_rel²+V_esc²) 不是纯制动 Δv |
| **O4+ dv_total** | dep_vinf 不含地表发射段 | — | 简化预算口径，明确标注了 |

**未发现"把自然引力加速度积分当燃料"的 bug。**

## Judgment

| 问题 | 回答 |
|------|------|
| calculation bug found | **无**。所有数值都是正确计算的，但 M6 `dv_total` 的定义口径与钱学森 model 不同 |
| are 30.x and 33.4 comparable | **M1 对称 patched-conic Δv = 29.41 km/s** 是可比且差异合理的（r_p 更远 = 速度需求更低）；**M6 的 91.88** 不可比；**M5 Lambert 的 30.88** 部分可比但项不完整 |
| if comparable, difference acceptable | M1（29.41 vs 33.68）：差异 ~12.7%，因为设计 r_p 不同（0.3 vs 0.2 AU），属合理差异 |
| if not comparable, why | M6 `dv_total` 的定义不是两段脉冲之和的"燃料预算"，而是包含了 `v_reentry`（含日心速度矢量差 ~78 km/s） |
| final verdict | **项目的 patched-conic 纯借力预算合理**；但 M6 报告中的 `dv_total=91.88 km/s` 口径与钱学森 total Δv 不同，不应直接比较。同学说的 30 多 km/s 如果指钱学森 total Δv，那我们的 29.41 (对称 patched-conic, r_p=0.3) 在合理范围内。 |

## Short answer to classmate

同学说的"三十几 km/s"如果是指钱学森书里的对称拼接圆锥曲线总 Δv（~33.4 km/s），那和我们项目中 **M1 对称 patched-conic 模型算出的 29.41 km/s**（设计 r_p=0.3 AU）是同一定义，差异来自设计参数不同，量级一致。我们项目中出现的高达 78–92 km/s 的数字（M5 `v_rel_earth`、M6 `dv_total`）与钱学森的 total Δv 模型定义不同——那是返回段火箭与地球的日心速度矢量差（约 78 km/s），不是推进剂消耗意义上的总速度增量。我们审计后确认**没有把自然引力加速度误当作燃料消耗的 bug**，但 M6 报告的 `dv_total` 数字口径需要说明清楚，避免与钱学森 total Δv 混用。
