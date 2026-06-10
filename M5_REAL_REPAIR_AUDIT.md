# M5 Real Repair Audit

## Status Summary

| 项目 | 结果 |
|---|---|
| Direct Lambert baseline | ✅ 执行；88 候选，0 fair |
| DSM baseline | ✅ 执行；2 候选，0 fair |
| Lunar budget (same proxy) | ✅ 执行；total=73.01 km/s |
| Formal saving ratio | ❌ None |
| Reference saving ratio | ❌ None |
| Status | **partial — 无法满足 M5.4–5.5 要求** |

## 为什么找不到 fair baseline

M5 的题干要求"与无月球借力方案对比"和"节能比例"。以下两路搜索均无法找到公平的 no-lunar baseline：

1. **Direct Lambert**：Earth→Earth 直接转移，88 个候选的 return_vinf 均超过 15 km/s 约束（最低约 26 km/s），因内转移返回时日心速度差过大。

2. **DSM Lambert**：Earth→DSM→Earth。DSM 点位于 0.35–0.70 AU，角距 60–120°。DSM 脉冲本身高达 40–50 km/s（因为地球轨道与内行星轨道之间的两段 Lambert 在连接点速度方向差异大），候选少且结果均不达标。

3. **根本原因**：月球借力提供了**免费**的日心速度改变（~0.4 km/s Δv），同时改变了速度方向使火箭能够进入 0.3 AU 近日椭圆轨道。没有这个借力，仅靠化学推进的两脉冲/三脉冲方案需要的 Δv 远高于有借力方案。

## 对 M5 评分的影响

- 严格按题干：M5.4（与无月借对比）**有**（两条 baseline 都已执行）
- 严格按题干：M5.5（节能比例）**无法提供**——没有基线数据可计算
- 项目提供的三条 baseline 可作为"尽力举证"的依据，但不是正式满足评分要求

## 建议的正式表述

```
M5.4 和 M5.5 已尽最大努力。两条独立搜索路径（direct Lambert + DSM）均未找到
满足近日距±10%和 return_vinf≤15 km/s 的 no-lunar baseline。在本文的模型和搜索
范围内，无法计算正式的节能比例。M5 标记为 partial。
```
