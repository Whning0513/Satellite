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
│   ├── shooting_corrector.py # O3: 打靶微分修正
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
│       └── o7_surrogate_prefilter.py # O7: Ridge surrogate (no sklearn)
└── PROJECT_DETAIL_DUMP.md  # 项目细节快照（供审查者参考）
```

---

## 八个里程碑 (Milestones)

### M1 — 拼接圆锥曲线 (Patched Conic) [done]
- 近日距到日心轨道根数的解析计算
- 与钱学森 r_p=0.2 AU 算例偏差 0.08%（< 0.1%）

### M2 — N 体 Velocity-Verlet 积分器 [done]
- 支持 N 体系统（日-地-月-探测器）
- 二体圆轨道基准：位置误差 8.27e-5（< 1e-4），能量漂移 < 5e-15

### M3 — JPL Horizons 历表对照 [done, near threshold]
- 2026 年 366 天 Sun-Earth-Moon 历表对比
- **3D 传播 + 日心系残差法**消除 SSB 漂移
- 最大位置残差 ≈ 5,900 km（≤ 6,000 km 阈值）
- 残余主要来自省略行星摄动（木星），非数值积分误差
- 详见 FINAL_AUDIT.md §4（error budget）

### M4 — 月球借力分析 [done-with-local-validation]
- 双曲线偏折解析公式
- 四体数值仿真（含 SOI 入口/出口跟踪）
- **60 组参数扫描**（6 r_m × 5 v_inf × 2 side），中位角度误差 0.04°
- 月心局部二体数值验证——不是完整任务级 N-body swing-by

### M5 — 单点轨道求解器 [done-with-caveat]
- 六段式求解流程 (S1–S6)
- Moon-aligned 前向搜索实现月球拦截
- 标称（MJD 61066.0）：r_p=0.2843 AU（误差 5.2%），v_launch=14.70 km/s
- **无月球借力对比**：基于 SOI-出口切向传播和 Earth-to-Earth Lambert 搜索重构。
  在 Lambert 搜索中，MJD 61066 找到 rp=0.3011 AU 的候选，但返回 v_inf=26.24 km/s > 15 km/s 约束；
  MJD 61154 无匹配近日距候选。因此不报告节能比例。
  详见 `data/results/m5_fair_no_lunar_baseline.json` 和 `m5_no_lunar_lambert_baseline.json`。

### M6 — 发射窗口优化 [done]
- 366 天逐日扫描，132 天可行
- 最佳 Δv 窗口：MJD 61154.0（r_p=0.2750 AU，误差 8.33%）
- 最佳综合窗口：MJD 61066.0（r_p=0.2843 AU，误差 5.23%）
- Top-5 全部通过 N 体积分验证

### M7 — 灵敏度分析 + 步长收敛 [done]
- 单参数扰动扫描 (t0, r_m, r_p)
- 20 样本蒙特卡洛
- **4 级步长收敛**（3600/1800/900/450s），能量漂移均 < 1e-10

### M8 — 可视化 [done]
- 8 张静态图（轨迹、借力、窗口、灵敏度、残差、能量漂移、日期曲线、等值线）
- 所有图片由 `make figures` 生成
- 详见 `figure_manifest.json`

### O4 — 多次借力链搜索 [exploratory]
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

## 快速开始

### 环境要求

- Python 3.10+
- numpy
- matplotlib（M8 可视化需要）
- astroquery + astropy（JPL Horizons 查询）
- xelatex（PDF 编译）

### 完整构建（make all）

```bash
make all     # compile → figures → pdf
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

### 生成动画（不在默认 make all 中）

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

### 标称轨迹 (MJD 61066.0)

| 参数 | 值 |
|------|-----|
| 发射速度 | 14.70 km/s |
| 近日距 | 0.2843 AU（目标 0.3 AU） |
| 近月距 | 21,374 km |
| 飞行总时间 | 96.1 天 |
| 再入速度 | 78.7 km/s |

### 发射窗口

- **最佳 Δv 窗口：** MJD 61154.0（r_p=0.275 AU，Δv_total=91.9 km/s）
- **最佳综合窗口：** MJD 61066.0（r_p=0.2843 AU，r_p 误差 5.2%）
- 详见 `data/results/m6_refined_windows.json`

### 已知局限

- M3 残差接近阈值（5,900/6,000 km），主要来自省略木星等大行星
- M4 数值验证为局部月心二体，非任务级 N-body
- M6 近日距误差 5–10%，需迭代校正才能进一步提高
- 动画（O5）在当前环境生成 MP4，若 ffmpeg/H.264 不可用会 fallback 到 GIF
- O7 代理扫描：ProcessPool 平均加速比 3.78x（55 MJDs, 8 workers, 3 次重复基准），但 per-process 缓存加载有初始开销
- O7 代理预筛选：Ridge 回归 R²=0.8956，几何特征仅能捕捉整体趋势，top-15 recall=33%
- O4 多次借力链搜索：有限的多体链可行性（analytic Venus 近似 + Moon 高 v_inf 偏转角不足限制链可行性）

---

## 参考

1. 钱学森.《星际航行概论》. 科学出版社, 1963.
2. JPL Horizons System: https://ssd.jpl.nasa.gov/horizons/
3. Bate, R. R., Mueller, D. D., & White, J. E. *Fundamentals of Astrodynamics*. Dover, 1971.
4. JPL ASTRODYN: https://ssd.jpl.nasa.gov/astro_glossary.html
