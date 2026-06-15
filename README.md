# MSPJ Final Project — 星际航行轨道设计与分析

## 项目概述

本项目实现了一个**星际航行轨道设计与分析系统**，基于钱学森《星际航行概论》中的轨道设计思想，结合现代 JPL 历表数据，实现从近地轨道到近日轨道的完整飞行方案设计。

核心任务：**利用月球借力实现从近地轨道到 0.3 AU 近日轨道的转移。**

### 关键技术指标

| 参数 | 目标值 |
|------|--------|
| 近地停泊轨道高度 | 0.1 R_Earth (637 km) |
| 设计近日距 | 0.3 AU |
| 近月距 | R_Moon + 500 km |
| 飞行时间 | < 2 年 |
| 再入速度 | < 15 km/s |

---

## 项目结构

```
FinalProject/
├── .gitignore             # 排除 config/、build/、大文件
├── Makefile               # 编译、验证、清理、审计
├── README.md              # 项目说明（本文件）
├── AI-Agent.md            # AI 辅助开发报告
├── FINAL_AUDIT.md         # 交付审计文件
├── config/
│   └── proxy.ini          # JPL 代理凭据（已 gitignored）
├── data/
│   ├── README.md
│   ├── sem_horizons_2026-2027.json  # JPL 历表缓存
│   └── results/                      # 所有结果输出（gitignored）
├── src/
│   ├── constants.py       # 物理常数与设计参数范围
│   ├── units.py           # 单位换算工具
│   ├── frames.py          # 参考系转换模块（日心/SSB/2D）
│   ├── dynamics.py        # 动力学引擎（SSB + 日心相对积分）
│   ├── nbody.py           # M2: N 体 Velocity-Verlet 积分器
│   ├── horizons.py        # M3: JPL Horizons 历表接口
│   ├── patched_conic.py   # M1: 拼接圆锥曲线
│   ├── lunar_swingby.py   # M4: 月球借力分析
│   ├── trajectory.py      # M5: 单点轨道求解器
│   ├── optimize_window.py # M6: 发射窗口优化
│   ├── sensitivity.py     # M7: 灵敏度分析
│   ├── plotting.py        # M8: 可视化
│   ├── animation.py       # O5: 轨道动画
│   ├── shooting_corrector.py # O3: 旧版打靶修正（legacy）
│   ├── diagnostics.py     # 时间/单位诊断
│   ├── validation.py      # 回归测试入口
│   └── experiments/       # 消融实验和辅助分析
│       ├── m3_residual_ablation.py
│       ├── m4_swingby_scan.py
│       ├── m7_stepsize_convergence.py
│       ├── aux_results.py
│       ├── o4_ephemeris_extend.py    # O4: Venus ephemeris extension
│       ├── o4_multi_gravity_assist.py # O4: Moon-Venus chain search
│       ├── o7_worker.py          # O7: ProcessPool worker
│       ├── o7_parallel_scan.py   # O7: ProcessPool parallel scan
│       ├── o7_surrogate_prefilter.py # O7: Ridge surrogate (no sklearn)
│       ├── m5_global_no_lunar_baseline.py # M5 global no-lunar baseline diagnostic
│       └── m6_pareto_window_diagnostic.py # M6 Pareto trade-off diagnostic
├── delta_v_budget.py       # Δv budget unified module
├── exp_statics/            # 归档审计、交接、追踪文档
│   ├── engineering_audit_archive.md
│   └── project_archive.md
└── AI-Agent.md             # AI 辅助开发报告
```

---

## 八个里程碑 (Milestones)

### M1 — 拼接圆锥曲线 (Patched Conic) [done]
- 近日距到日心轨道根数的解析计算
- 与钱学森 r_p=0.2 AU 算例偏差 0.08%（< 0.1%）

### M2 — N 体 Velocity-Verlet 积分器 [done]
- 支持 N 体系统（日-地-月-探测器）
- 二体圆轨道基准：位置误差 8.27e-5（< 1e-4），能量漂移 < 5e-15

### M3 — JPL Horizons 历表对照 [model hierarchy]
- 同一定义、同一采样下的保真度递进链
- **SEM_3body**（基线）：天文 5912 km，通过 6000 km 阈值
- **SEM+Jupiter+Venus_5body**：实际积分，残差 1401 km（改善 76.3%）
- **SEM_full_planetary**（10 体）：残差仅 126 km（改善 97.9%）
- 证明 3-body 残差主要由省略大行星摄动（木星）引起，非数值误差
- 详见 `data/results/m3_model_hierarchy.json`

### M4 — 月球借力分析 [done-with-local-validation]
- 双曲线偏折解析公式
- 四体数值仿真（含 SOI 入口/出口跟踪）
- **60 组参数扫描**（6 r_m × 5 v_inf × 2 side），中位角度误差 0.04°
- 月心局部二体数值验证——不是完整任务级 N-body swing-by

### M5 — 单点轨道求解器 [done-with-caveat]
- 六段式求解流程 (S1–S6)
- Moon-aligned 前向搜索实现月球拦截
- 合法 formal 锚点：MJD 61065.0（2026-01-25），`trailing`，`r_m=1837.4 km`
- 返回地球距离 446,151 km，`return_vinf=10.5173 km/s`
- 同日 no-lunar DSM baseline：`total_vinf_basis=20.5938 km/s`
- 当前正式 fixed-date saving ratio：`50.85%`
- 详见 `data/results/m5_best_lunar_candidate_verify.json` 和 `m5_fixed_date_current_compare.json`

### M6 — 发射窗口优化 [done-with-caveat]
- 已实现 2026 全年几何窗口粗筛与候选提取
- 历史 61066/61154 不再作为 formal 最优窗口
- 当前正式窗口身份：`legal-window verified anchor = MJD 61065.0`
- 如需声明全年全局最优，仍需重跑完整合法窗口搜索

### M7 — 灵敏度分析 + 步长收敛 [done-with-caveat]
- 锚点已切换到合法 formal candidate（MJD 61065.0）
- Full Monte Carlo：`N=200`，`valid=38`，`invalid=40`，`timeout=122`
- formal `return_vinf` 只在真实 Earth-return event 上定义，旧伪 ~79 km/s 已阻断
- **4 级步长收敛**（3600/1800/900/450s），能量漂移均远低于阈值

### M8 — 可视化 [done-with-caveat]
- 当前提交物可直接引用 7 张静态图（轨迹、借力、窗口、灵敏度、能量漂移、日期曲线、等值线）
- 所有图片由 `make figures` 生成
- 详见 `figure_manifest.json`

### O3 — 自定义微分修正器 [done-with-caveat]
- 从 1-param angle 升级为多参数 damped Gauss-Newton（2-param: angle + scale）
- 审计发现目标泄漏 bug 并修复；改善约 4×（离收敛尚远）
- 框架完整（无 scipy，Jacobian, line search, Tikhonov, multi-start）
- 文件：`src/experiments/o3_differential_corrector.py`；运行：`make o3`

### O3+ — 矢量微分修正器 [done]
- 直接 delta_v 速度修正 + Levenberg-Marquardt 阻尼（无 scipy）
- 3-param: delta_vx, delta_vy, tof_shift_days
- **74.59× 改善，最终偏差 66,210 km < 100,000 km 阈值**
- 11 个多起点，5/11 useful（改善 ≥ 10×）
- dv_norm=1.22 km/s，速度残差合理（22.1 km/s）
- 文件：`src/experiments/o3plus_vector_differential_corrector.py`；运行：`make o3plus`

### O4 — 多次借力链搜索 [frozen exploratory]
- Earth-Moon-Venus-Earth patched-conic 链搜索
- Venus 历表：analytic circular fallback（无网络时离线可用）
- 三段 Lambert：地球出发→月球→金星→地球返回
- **O4 已冻结（commit 18fa865），不覆盖**

### O4+ — 多次借力优化器 [done; no feasible powered candidate found]
- 在 O4 的 Lambert 链基础上允许 powered flyby residual（Moon/Venus 小速度脉冲）
- 两阶段优化：粗网格 19200 组合 + pattern search 精修
- **142 个 Lambert 成功候选，0 个 feasible_powered**
- 确认 O4 结论：Earth-Moon-Venus-Earth 链即使允许 powered flyby residual 也难以实现
- O4+ 不覆盖 O4，是独立增强任务
- 文件：`src/experiments/o4plus_powered_mga_optimizer.py`；运行：`make o4plus`
- Earth-Moon-Venus-Earth patched-conic 链搜索
- Venus 历表：analytic circular fallback（无网络时离线可用）
- 三段 Lambert：地球出发→月球→金星→地球返回
- 含飞越可行性判断（required-turn vs available-turn at min periapsis）
- ~8400 条链路组合中 98 条三段 Lambert 成功收敛（保留候选）
- 主要限制：月球在高 v_inf（~10 km/s）下最大偏转角仅 ~3°，限制链可行性
- 文件：`src/experiments/o4_ephemeris_extend.py`、`o4_multi_gravity_assist.py`

### O7 — 并行扫描与代理预筛选 [done]
- ProcessPoolExecutor batching 替代 ThreadPoolExecutor（旧方案 GIL 限制，仅 0.56×）
- 55 天测试集：平均 3.78× 加速比（3 次重复基准，55/55 结果一致）
- Ridge 回归代理预筛选器（无 sklearn 依赖，闭式解实现）
- 6 个几何特征预测实现近日距，R²=0.8956，MAE=0.059 AU
- Top-15 召回率 33.3% — 可捕捉趋势但不可替代物理 N 体扫描
- 文件：`src/experiments/o7_worker.py`、`o7_parallel_scan.py`、`o7_surrogate_prefilter.py`
- 运行：`make o7-parallel` / `make o7-surrogate`

---

### Diagnostics (do not replace M1-M8)
- `make delta-v-audit`: Unified Δv budget classification and comparison to Qian 33.4
- `make m5-global-baseline`: Broader no-lunar baseline search (supports existing M5 caveat)
- `make m6-pareto`: Pareto trade-off analysis for launch windows
- `make polish-diagnostics`: Run all three
- Files: `src/delta_v_budget.py`, `src/experiments/m5_global_no_lunar_baseline.py`, `src/experiments/m6_pareto_window_diagnostic.py`

---

## 快速开始

### 环境要求

- Python 3.10+
- numpy
- matplotlib（M8 可视化需要）
- astroquery + astropy（JPL Horizons 查询）
- xelatex（PDF 编译）

### 完整构建（make all）

```bash
make all     # compile → m3 → figures → animation → m5 baselines → pdf
```

### 常用命令

```bash
make compile      # 语法检查
make validate     # 全部回归测试
make figures      # 生成全部图表
make pdf          # 编译 report.pdf
make audit        # 安全审计 + 图表完整性检查
make clean        # 清理生成物
```

### 生成全部回归测试

```bash
make validate
```

这将依次运行 m1 到 m8 的回归测试。

### 运行单个里程碑测试

```bash
make m1   # 拼接圆锥曲线
make m2   # N 体积分器
make m3   # JPL 历表对照
make m4   # 月球借力
make m5   # 单点轨道求解
make m6   # 发射窗口优化
make m7   # 灵敏度分析
make m8   # 可视化
```

### 动画输出（已包含在 make all 中）

```bash
make animation    # 依赖 figures，生成 45 秒 MP4 + 4 张关键帧
```

- 输出 MP4：`build/orbit_animation.mp4`（若 ffmpeg/H.264 可用）
- 降级输出：`build/orbit_animation.gif`（若 ffmpeg 不可用）
- 关键帧：`data/results/animation_keyframe_*.png`
- 轨迹缓存：`data/results/animation_trajectory.json`
- MP4/GIF 不进入 Git（`build/` 已 gitignore）

---

## 物理模型

### 坐标系

- **主计算：** SSB 惯性系（N 体积分在此进行）
- **残差对比：** 日心相对坐标（事后变换，非拟合）
- **显示：** J2000 黄道平面（二维投影）
- 参考系转换统一由 `src/frames.py` 管理

### 引力模型

3 体系统：太阳、地球、月球（火箭作为 test particle，GM=0）

### 积分方法

Velocity-Verlet 算法：
- 主步长 DT_MAIN = 3600 s
- 细化步长 DT_REFINE = 60 s

动力学引擎支持 SSB 惯性系和日心相对坐标（含 indirect term），见 `src/dynamics.py`。

### M3 参考系统一

SSB 惯性积分 → 日心系残差对比，消除因省略大行星摄动导致的共同漂移。
这一方法在 ablation 实验（E3/E4）中验证与日心相对坐标积分（E6）等价。

### 安全说明

`config/proxy.ini` 包含 JPL 代理凭据，已被 `.gitignore` 排除。
运行 `make audit` 可自动检查是否有凭据泄露。

---

## 结果摘要

### 当前正式 fixed-date 结果（合法 2026 发射窗）

| 参数 | 值 |
|------|-----|
| 发射日期 | 2026-01-25（MJD 61065.0） |
| 发射超速 | 10.1213 km/s |
| 表面发射等效速度 | 15.0809 km/s |
| 实现近日距 | 0.274959 AU |
| 返回地球距离 | 446,151 km |
| 返回 v_inf | 10.5173 km/s |
| 飞行总时间 | 96.12 天 |

### 同日 no-lunar 对比

- **lunar total_vinf_basis：** 10.1213 km/s
- **no-lunar DSM total_vinf_basis：** 20.5938 km/s
- **formal saving ratio：** 50.85%
- 该比较仅在相同 t0、相同 budget basis、均满足真实 Earth-return event 时成立

### 已知局限

- M3 是 same-source propagation check，不是独立 JPL 预测精度证明
- M4 数值验证为局部月心二体/局部任务参数对照，非完整任务级 high-fidelity swingby
- M6 当前正式身份是 legal-window verified anchor；尚未把全年全局最优重新重建完毕
- M7 full MC 存在大量 timeout，当前更像 event-search 能力瓶颈，不宜直接解释为物理上全部不返回
- 动画（O5）优先生成 MP4，若 ffmpeg/H.264 不可用会 fallback 到 GIF
- O7 代理预筛选：Ridge 回归 R²=0.8956，几何特征仅能捕捉整体趋势，top-15 recall=33%
- O4 多次借力链搜索：有限的多体链可行性（analytic Venus 近似 + Moon 高 v_inf 偏转角不足限制链可行性）

---

## 参考

1. 钱学森.《星际航行概论》. 科学出版社, 1963.
2. JPL Horizons System: https://ssd.jpl.nasa.gov/horizons/
3. Bate, R. R., Mueller, D. D., & White, J. E. *Fundamentals of Astrodynamics*. Dover, 1971.
4. JPL ASTRODYN: https://ssd.jpl.nasa.gov/astro_glossary.html
