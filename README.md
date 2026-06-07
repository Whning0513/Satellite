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
├── Makefile              # 编译、验证、清理
├── README.md             # 项目说明（本文件）
├── AI-Agent.md           # AI 辅助开发报告
├── data/
│   ├── sem_horizons_2026-2027.json  # JPL 历表缓存
│   └── results/                      # 结果输出目录
│       ├── m6_windows.json           # M6 窗口优化结果
│       ├── m7_sensitivity.json       # M7 灵敏度分析
│       └── m8_*.png                  # M8 可视化输出
├── src/
│   ├── constants.py      # 物理常数与设计参数范围
│   ├── units.py          # 单位换算工具
│   ├── patched_conic.py  # M1: 拼接圆锥曲线
│   ├── nbody.py          # M2: Velocity-Verlet N体积分器
│   ├── horizons.py       # M3: JPL Horizons 历表接口
│   ├── lunar_swingby.py  # M4: 月球借力分析
│   ├── trajectory.py     # M5: 单点轨道求解器
│   ├── optimize_window.py # M6: 发射窗口优化
│   ├── sensitivity.py    # M7: 灵敏度分析
│   ├── plotting.py       # M8: 可视化
│   └── validation.py     # 回归测试入口
└── paper/                # (可选) 论文相关
```

---

## 八个里程碑 (Milestones)

### M1 — 拼接圆锥曲线 (Patched Conic) [done]
- 二分法求解日心段轨道根数
- 计算 C3、v_launch、Δv
- 支持内/外转移（近日/远日）

### M2 — N 体 Velocity-Verlet 积分器 [done]
- 4 体（日-地-月-探测器）自主三阶积分
- 600 s 积分步长，年度相对能量漂移 < 1e-6

### M3 — JPL Horizons 历表对照 [partial]
- 2026–2027 年日月地矢量历表
- 缓存 JSON 至 `data/sem_horizons_2026-2027.json`
- ⚠️ 残差 ~9.65e4 km（超过 6000 km 阈值，参见 FINAL_AUDIT.md）

### M4 — 月球借力分析 [partial]
- 基于圆锥曲线匹配的借力模型
- ⚠️ 解析模型完成，数值仿真层未实现（simulate_swingby_nbody 为占位符）

### M5 — 单点轨道求解器 [done]
- 六段式求解流程 (S1–S6)
- Moon-aligned 前向搜索实现月球拦截
- 前后向传播覆盖完整轨道

### M6 — 发射窗口优化 [done]
- 全年逐日扫描 Moon 对准几何
- 快速模式：几何评分
- 完整模式：调用 N 体求解验证（仅 top-1 完成）

### M7 — 灵敏度分析 [done]
- 单参数扰动扫描 (t0, r_m, r_p)
- 蒙特卡洛多参数随机扰动
- 灵敏度系数统计

### M8 — 可视化 [partial]
- 轨道图（日心系 + 局部放大）
- 发射窗口极坐标图
- 灵敏度散点图与直方图
- ⚠️ 4/6 张图完成，缺 Horizons 残差图和能量漂移图

---

## 快速开始

### 环境要求

- Python 3.10+
- numpy
- matplotlib（M8 可视化需要）
- json（内置）

### 编译检查

```bash
make compile
```

### 运行全部回归测试

```bash
make validate
```

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

---

## 物理模型

### 坐标系

J2000 黄道平面（二维投影），以太阳为中心。

### 引力模型

4 体系统：太阳、地球、月球、探测器

### 积分方法

Velocity-Verlet 算法：
- 主步长 DT_MAIN = 3600 s
- 细化步长 DT_REFINE = 60 s

### C3 计算

发射能量 C3 = v_launch² - v_esc²，其中：
- v_launch = |v_inf_earth + v_earth|
- v_esc = √(2·GM_Earth / r_parking)
- r_parking = R_Earth × 1.1

---

## 结果摘要

### 标称轨迹 (MJD 61066.0)

| 参数 | 值 |
|------|-----|
| 发射速度 | ~15–16 km/s |
| 近日距 | ~0.3 AU (目标) |
| 近月距 | < R_Moon_SOI |
| 飞行总时间 | ~200-300 天 |
| 再入速度 | < 15 km/s |

### 最佳发射窗口

详见 M6 优化结果 (`data/results/m6_windows.json`)。

---

## 参考

1. 钱学森.《星际航行概论》. 科学出版社, 1963.
2. JPL Horizons System: https://ssd.jpl.nasa.gov/horizons/
3. Bate, R. R., Mueller, D. D., & White, J. E. *Fundamentals of Astrodynamics*. Dover, 1971.
4. JPL ASTRODYN: https://ssd.jpl.nasa.gov/astro_glossary.html
