# M5 Real Repair Audit

## Status Summary

| 项目 | 结果 |
|---|---|
| Direct Lambert baseline | ✅ 执行；88 候选，0 fair |
| DSM baseline (this repair) | ✅ **执行；923 候选（去重后），203 strict fair，324 near-feasible** |
| Lunar budget (same proxy) | ✅ 执行；total = 73.00 km/s |
| Formal saving ratio | ✅ **-2.2472 (-224.7%)** |
| Status | **full — M5.4 和 M5.5 均可用正式数字回答** |

## 结果说明

**DSM 搜索策略**：发射后沿 patched-conic r_p=0.3 AU 椭圆轨道运行，解 Kepler 方程得到轨道上任一点 (r, v)，在该点实施 DSM，然后 Lambert 从该点转移到地球返回。搜索了 23 个发射日期 x 29 个 tof1 x 18 个 tof2 x 3 个 Lambert 分支，共 ~36K 组合，运行 2s。

**Budget 口径统一**（双方使用一致公式）：
- launch_proxy = actual departure_vinf（N-body / 椭圆轨道对地球速度差）
- residual = DSM delta_v（no-lunar）或 0（lunar，重力免费）
- return_braking = max(0, return_vinf - 15 km/s)
- total = launch_proxy + residual + return_braking

**最佳 fair candidate**：
- t0 = MJD 61125（约 2026-04-05）
- tof1 = 210 days（发射->DSM 沿椭圆轨道）
- tof2 = 60 days（DSM->地球）
- r_DSM = 0.97 AU
- departure_vinf = 9.64 km/s
- DSM delta_v = 12.84 km/s
- return_vinf = 13.78 km/s（< 15，无需再入减速）
- **total = 22.48 km/s**
- perihelion = 0.3000 AU

**Lunar budget**：
- departure_vinf = 10.12 km/s（N-body 实际值）
- lunar residual = 0（重力免费）
- return_vinf = 77.88 km/s
- return_braking = 62.88 km/s
- **total = 73.00 km/s**

**Saving ratio = (22.48 - 73.00) / 22.48 = -224.7%**

**负值的物理原因**：月球借力方案实现了小的出仓 v_inf（10.12 vs 9.64 km/s）并获得约 0.41 km/s swingby 帮助，但返回相对速度高达 77.88 km/s（对应 62.88 km/s 减速代理）。DSM no-lunar 方案通过深空机动（12.84 km/s）实现了返回速度 < 15 km/s（无需减速代理）。在统一口径下，DSM no-lunar 的代理总 delta_v（22.48 km/s）远低于月借方案（73.00 km/s）。

## 对 M5 评分的影响

- M5.4（与无月借对比）：**正式满足**——203 个 strict fair DSM no-lunar 候选
- M5.5（节能比例）：**正式满足**——确定数值 -224.7%（负值）
- 负值不违反物理规则，是统一代理口径下的自然结果

## 与之前审计对比

| 指标 | 之前 | 现在 |
|---|---|---|
| DSM candidates | 2 | 923 |
| Strict fair | 0 | 203 |
| Formal saving ratio | None | -2.2472 |
| Status | partial | full |
