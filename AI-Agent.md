# AI-Agent.md — AI 辅助开发报告

## 概述

本项目全程使用 **Claude Code (Anthropic Claude 4.7)** 作为 AI 编程助手进行开发。AI 参与了从架构设计、代码生成、调试修复到验证测试的全流程。

---

## 开发模式

采用 **对话-生成-验证-迭代** 的协作模式：

1. **需求分析**：人类提出里程碑目标，AI 解析物理模型与算法约束
2. **架构设计**：AI 提出模块划分、数据流、接口定义
3. **代码生成**：AI 生成完整模块代码，人类审定
4. **回归测试**：每个模块附带 `_run_mX_regression()` 测试用例
5. **调试修复**：物理错误或数值异常时，AI 分析根因并提出修复方案
6. **优化迭代**：人类反馈结果，AI 调整参数或算法

---

## 各里程碑开发过程

### M1 — 拼接圆锥曲线 (patched_conic.py)

- **AI 角色**：独立生成
- **关键决策**：使用二分法替代解析公式求近日距
- **验证策略**：对 Δv 符号、v_launch 范围、飞行时间进行合理性断言

### M2 — N 体 Velocity-Verlet 积分器 (nbody.py)

- **AI 角色**：独立生成
- **关键决策**：主步长 3600 s，细化步长 60 s；能量守恒检查每 1000 步一次
- **验证策略**：年度能量漂移 < 1e-6

### M3 — JPL Horizons 历表 (horizons.py)

- **AI 角色**：独立生成 + 代理补丁
- **关键决策**：使用 `requests` 获取，缓存 JSON；代理环境不可用则使用预缓存数据
- **验证策略**：位置/速度连续性检查

### M4 — 月球借力 (lunar_swingby.py)

- **AI 角色**：独立生成
- **关键决策**：基于圆锥曲线匹配的借力模型，支持 leading/trailing 两种模式
- **挑战**：三次迭代修正 turn angle 计算，AI 通过分析 Δv 曲线收敛到正确物理

### M5 — 单点轨道求解器 (trajectory.py)

- **AI 角色**：主要生成 + 物理修复
- **关键挑战**：**内转移的 retrograde 发射方向** — AI 最初默认 prograde，导致 r_p 偏差 20 倍。人类指出物理问题后，AI 重新推导 C3 公式并修正 v_inf_dir 参数。
- **解决方案**：
  - 内转移 (r_p < 1 AU) 使用 retrograde 发射（反地球公转方向）
  - Delta_v < 0 表示减速发射
  - Moon-aligned 前向搜索逐步逼近月球位置
- **验证策略**：6 个断言覆盖 C3、近月距、近日距、再入速度

### M6 — 发射窗口优化 (optimize_window.py)

- **AI 角色**：独立生成
- **算法**：两阶段策略
  1. 快速阶段：几何评分（Moon 与 v_inf 方向夹角）
  2. 完整阶段（可选）：N 体求解前 N 个候选
- **设计考量**：C3 对固定 r_p 为常量，不随 t0 变化，因此仅需几何对准评分

### M7 — 灵敏度分析 (sensitivity.py)

- **AI 角色**：独立生成
- **方法**：
  - sweep_parameter：单参数扰动扫描（t0, r_m, r_p）
  - monte_carlo_analysis：多参数高斯随机扰动
  - compute_sensitivity：统计汇总
- **验证策略**：至少有一个扰动扫描成功

### M8 — 可视化 (plotting.py)

- **AI 角色**：独立生成
- **图形内容**：
  - 日心系轨道图（含太阳、地球轨道、月球轨道、火箭路径）
  - 月球借力局部放大图
  - 发射窗口极坐标雷达图
  - 灵敏度散点图 + MC 直方图
- **技术选型**：matplotlib "Agg" 后端，支持无 GUI 环境

---

## 关键技术挑战与 AI 解决方案

### 1. 内转移物理方向

- **问题**：M5 最初假设 prograde 发射，导致近日距为 0.6 AU 而非 0.3 AU
- **AI 分析**：推导 C3 关系发现 v_inf_earth 需要大减速，实际 Delta_v < 0
- **修复**：添加 `delta_v < 0 → retrograde` 逻辑

### 2. 月球拦截算法设计

- **问题**：月球拦截需要同时满足时间和空间对准
- **AI 方案**：前向传播 + 位置差最小化搜索，主步长定位 + 精细步长修正

### 3. 灵敏度分析效率

- **问题**：完整 M7 需运行数百次 N 体求解
- **AI 方案**：小规模回归测试（20 MC 样本 + 6 扰动点），完整分析留给正式运行

### 4. 可视化与回归测试解耦

- **问题**：M8 需要 M5 的求解结果，但回归必须独立
- **AI 方案**：`_run_m8_regression()` 内部自包含 M5 求解调用

---

## 缺陷与限制

### 已知限制

1. **JPL 代理环境**：AI 运行环境无法直接访问 JPL Horizons API，使用预缓存数据
2. **二维近似**：j2000 黄道平面投影，忽略倾角分量
3. **MC 样本量有限**：回归测试仅 20 样本，生产建议 >1000
4. **无可视化交互**：matplotlib 仅保存文件，不启动 GUI
5. **V_inf 匹配机制**：月球拦截的 Δv 分配在侧向接近时存在收敛奇异

### 数值精度

- 积分器能量漂移：< 1e-6/年
- 位置误差（vs 二体解析）：< 1e-5 AU
- 近日距误差：< 25% 对于优化目标可接受

---

## 代码统计

| 模块               | 行数            | 功能         |
| ------------------ | --------------- | ------------ |
| constants.py       | 94              | 物理常数     |
| units.py           | 67              | 单位换算     |
| patched_conic.py   | 305             | 拼接圆锥曲线 |
| nbody.py           | 520             | N 体积分器   |
| horizons.py        | 372             | JPL 历表     |
| lunar_swingby.py   | 380             | 月球借力     |
| trajectory.py      | 560             | 轨道求解器   |
| optimize_window.py | ~340            | 窗口优化     |
| sensitivity.py     | 442             | 灵敏度分析   |
| plotting.py        | ~420            | 可视化       |
| validation.py      | 102             | 测试入口     |
| **总计**     | **~3600** |              |

---

## Final polish phase with AI assistance

### Architecture refactoring (frames.py, dynamics.py, diagnostics.py)

- **Claude Code 角色**：独立生成
- **生成内容**：
  - `src/frames.py`：参考系转换模块（`to_heliocentric`, `to_barycentric`, `project_to_2d`, `relative_state`）
  - `src/dynamics.py`：动力学引擎（`accel_barycentric`, `accel_heliocentric_relative` 含 indirect term）
  - `src/diagnostics.py`：Horizons 时间/单位诊断
- **人工审定**：所有数值结果与原有 nbody.py 对比，确认等价

### M3 残差消融实验

- **Claude Code 角色**：设计实验方案并生成代码
- **实验内容**：7 种模式（E0–E6），覆盖 2D/3D、SSB/日心相对、多级步长
- **关键发现**：E3 与 E6 结果一致（5,900 km），确认日心相对动力学与 SSB 积分后转换等价
- **人工审定**：确认 ablation 不用于冒充主结果，E4（SSB+日心对比）作为最终模式

### M4 参数扫描

- **Claude Code 角色**：生成扫描脚本
- **扫描网格**：6 r_m × 5 v_inf × 2 side = 60 组
- **结果**：中位角度误差 0.04°，max 角度误差 23°（低 v_inf、leading 侧）
- **人工审定**：确认不能声称"完整高保真"N-body 验证

### M7 步长收敛分析

- **Claude Code 角色**：生成收敛分析脚本
- **测试步长**：3600, 1800, 900, 450 s
- **结论**：r_p 在 ≤1800s 稳定于 0.2845 AU，能量漂移全 &lt; 1e-10

### M6 综合排名

- **Claude Code 角色**：设计 balanced score（Δv + r_p 误差惩罚）
- **区分 best_by_dv 和 best_balanced**
- **明确文档**：MJD 61154.0 wins by dv, MJD 61066.0 has better r_p accuracy

### 审计与提交准备

- **Claude Code**：生成 FINAL_AUDIT.md、PROJECT_DETAIL_DUMP.md、校对 README
- **人工审定**：所有数值来自实际脚本输出，非 AI 编造；阈值和状态判断经人工检查

### 本轮 AI 使用原则

1. 所有数值结果来自实际运行的回归测试和扫描脚本
2. AI 未直接修改阈值或编造指标
3. 人工最终检查状态表述（"done" vs "done-with-simplification"）
4. 局限性章节保留并更新

## 参考

- Claude Code CLI — Anthropic 官方 CLI 工具
- Claude 4.x Series — 支撑本项目的 AI 模型
- [项目 README](./README.md)
