# PROJECT FINAL HANDOFF

## Branches and commits

| Branch | Latest Commit | Description |
|--------|--------------|-------------|
| `master` | `88d3a09` | 正式提交版。M1–M8 全部通过，PDF 28 页，离线可复现，token 无泄露 |
| `bonus-extensions` | `e8dea8f` | O5 45s MP4 动画、O3 exploratory shooter、O1 轻量 3D diagnostic |
| `all-bonus-complete` | `a3e5e72`（当前分支） | 全加分项 + M5 废弃旧 -430% saving、替换为 SOI-exit + Lambert baseline |

- **当前分支**: `all-bonus-complete`
- **git status**: ✅ CLEAN
- **已推送远端**: ❌ 未推送（Gitea 仓库尚未创建）

---

## Mandatory tasks M1–M8

| Item | Status | Evidence | Caveat |
|------|--------|----------|--------|
| **M1** patched conic | ✅ done | `patched_conic.py`; error 0.08% vs Qian 0.2 AU | 无 |
| **M2** N-body integrator | ✅ done | `nbody.py`; pos_err 8.27e-5, energy drift <5e-15 | 无 |
| **M3** JPL Horizons | ✅ done, near threshold | 3D + heliocentric compare; Earth 5,897 km, Moon 5,900 km ≤6,000 km; ablation E0–E6 | 阈值 98.3%；主要来自缺失行星摄动 |
| **M4** lunar swingby | ✅ done-with-local-validation | 60 组 perifocal+DOP853 扫描; finite-SOI error 0.0°; median inf_err 0.03° | 月心局部二体，非完整 N-body swingby |
| **M5** trajectory + no-lunar comparison | ✅ done-with-caveat | 三层 baseline: patched-conic(废弃)、SOI-exit、Earth-to-Earth Lambert | 旧 -430% saving 已废弃；MJD 61066 找到 rp=0.3011 AU 但 return v_inf=26.24 >15；MJD 61154 无匹配；不计算 saving ratio |
| **M6** launch window | ✅ done | 366 天扫描 + top-5 N 体 + Δv audit + lexicographic ranking | 最佳 Δv 和最佳平衡窗口不同；rp 误差 5–10% |
| **M7** sensitivity | ✅ done | 扰动扫描 + 20 MC + 4 级步长收敛（2 阶 ✅） | r_p 响应不光滑导致收敛阶不稳定 |
| **M8** visualization | ✅ done | 8 PNG + figure_manifest + `make figures` 全额生成 | 无 |

---

## M5 Final State

| 项 | 值 |
|----|-----|
| **commit hash** | `a3e5e72`（文档封存） |
| **最终状态** | done-with-caveat |

### MJD 61066

| 指标 | 值 |
|------|-----|
| Lambert candidates | 358 |
| Feasible (rp<10% + return_v_inf ≤15 km/s) | **0** |
| Near-feasible (rp<10% + 15 < return_v_inf ≤25) | **14** |
| Best rp | 0.3011 AU (error 0.4%) |
| Best tof | 271.5 days |
| Best branch | prograde_long |
| Best return v_inf | 26.24 km/s |
| Comparison status | **partial_tradeoff** |

### MJD 61154

| 指标 | 值 |
|------|-----|
| Lambert candidates | 380 |
| Feasible | **0** |
| Near-feasible | **0** |
| Best rp | 0.4721 AU |
| Return v_inf | 64.06 km/s |
| Comparison status | **invalid_no_matching_perihelion** |

### Saving ratio

**不报告**。两个 t0 均未找到同时满足 rp 匹配和再入约束的 no-lunar 候选。

### Evidence files

| File | Description |
|------|-------------|
| `data/results/m5_fair_no_lunar_baseline.json` | SOI-exit tangent propagation |
| `data/results/m5_no_lunar_lambert_baseline.json` | Earth-to-Earth Lambert search |
| `data/results/m5_no_lunar_lambert_pareto.json` | Pareto frontier (rp_error vs return v_inf) |
| `data/results/m5_no_lunar_lambert_pareto.png` | Pareto plot |
| `M5_FINAL_HANDOFF.md` | Detailed M5 handoff |

### Do not modify M5 further

Current fixed-date Lambert search is sufficient. Do not re-enter M5 without a project-wide no-lunar search expansion.

---

## Optional tasks O1–O7

| Item | Status | Evidence | Remaining Problem |
|------|--------|----------|-------------------|
| **O1** 3D extension | ✅ diagnostic | `o1_3d_comparison.json`; Moon z ~39,000 km, Earth 2D→3D diff ~12,600 km | 不替代主线 2D 结果 |
| **O2** GR correction | ✅ done | `o2_relativity.json`; a_GR/a_N ≈ 6.7e-8, Δr_p < 1 km | 效应极小，对本项目无实质影响 |
| **O3** shooting corrector | ⚠️ done-with-caveat | `o3_shooting_corrector.json`; O3: angle/scale GN ~4x after leak fix; O3+: vector LM 74.59x, final 66,210 km < 100k threshold | O3+ fully converged at 100k threshold. O3 kept as done-with-caveat (leak fix documented). Not integrated into main pipeline. |
| **O4** multi-gravity assist | ⚠️ exploratory | `o4_multi_gravity_assist.json`; 98 Lambert chain candidates (Earth-Moon-Venus-Earth); analytic Venus fallback; best return v_inf=13.38 km/s; 0 feasible-ish | Moon flyby turn ~3 deg at high v_inf, Venus insufficient; chain not feasible in patched-conic framework |
| **O5** orbit animation | ✅ done | 45s, 24fps, h264 MP4 (`build/orbit_animation.mp4`, gitignored) + 4 keyframes + poster | 无（编码器自动降级） |
| **O6** interactive demo | ✅ done | `interactive_demo.py` + `o6_interactive_screenshot.png` | 需本地 Tkinter/Matplotlib GUI |
| **O7** parallel scan | ✅ done | `o7_parallel_scan.json`; ProcessPool mean 3.78x (3-run bench, 55/55 identical); Ridge R2=0.8956, no sklearn | ProcessPool chunked batching + Ridge surrogate prefilter (6 geometric features, closed-form) |

### Not attempted

- O2 已做（已覆盖）
- O6 已做（已覆盖）

---

## Current strongest remaining issues

| Priority | Item | Problem | Suggested approach |
|----------|------|---------|-------------------|
| **1** | O4 multi-gravity assist | Lambert chain framework built (98 candidates). No feasible-ish candidate due to Moon/Venus turn deficit at high v_inf. Analytic circular Venus fallback. | **O4 frozen at `18fa865`. O4+ (powered MGA optimizer) built as separate extension: 142 Lambert candidates, 0 feasible-powered. Confirms O4 conclusion.** |
| ~~2~~ | ~~O7 parallel scan~~ | ~~resolved~~ | ProcessPool mean 3.78x + Ridge R2=0.8956 surrogate prefilter implemented (3-run benchmark, 55/55 identical)
| ~~3~~ | ~~O3/O3+ correctors~~ | ~~resolved~~ | O3 (done-with-caveat, leak-fix documented) + O3+ (done, vector LM converged < 100k km). Both frozen. |
| **4** | Final push | No remote configured | Create Gitea repo, push both `master` and `all-bonus-complete` |

---

## Validation status (last full run)

| Check | Result |
|-------|--------|
| `python -m compileall src` | ✅ PASS |
| `make validate-m5` | ✅ PASS |
| `make audit` | ✅ PASS |
| `make pdf` | ✅ PASS (33 pages) |
| PDF pages | **33** (<40 ✅) |
| Tracked repo size | **~0.69 MB** (<10 MB ✅) |
| Large files outside build/ | none |
| Token check | ✅ PASS (config/ gitignored) |
| git status | ✅ CLEAN |
