# PROJECT DETAIL DUMP — MSPJ FinalProject

Generated: 2026-06-07
Purpose: Snapshot for external reviewer analysis.

---

## 1. Repository overview

- **Current directory:** `D:\Desktop\mspj\FinalProject\src`
- **Project root:** `D:\Desktop\mspj\FinalProject`
- **Git repository:** Yes (no remote configured; working directory is `src/`)
- **Current branch:** Not tracked (no .git in src/ — git is at project root)
- **Uncommitted files:** All files are untracked (`?? .gitignore`, `?? Makefile`, `?? src/`, etc.) — appears to be a fresh checkout or git not yet initialized at project level
- **Repo size (src only from within src):** 505K (source + __pycache__); full project root ~505K
- **Large files (>5MB):** None found

### File tree (top 3 levels)

```
FinalProject/
├── .gitignore
├── AI-Agent.md
├── Makefile
├── PROJECT_DETAIL_DUMP.md      (this file)
├── README.md
├── report.tex
├── config/
│   └── proxy.ini
├── data/
│   ├── README.md
│   ├── sem_horizons_2026-2027.json   (248 KB — Horizons cache)
│   └── results/                      (15 files: JSON + PNG + GIF)
└── src/
    ├── animation.py
    ├── constants.py
    ├── diagnostics.py
    ├── dynamics.py
    ├── frames.py
    ├── horizons.py
    ├── jpl_forward.py
    ├── lunar_swingby.py
    ├── nbody.py
    ├── optimize_window.py
    ├── patched_conic.py
    ├── plotting.py
    ├── sensitivity.py
    ├── shooting_corrector.py
    ├── trajectory.py
    ├── units.py
    ├── validation.py
    └── experiments/
        ├── __init__.py
        └── m3_residual_ablation.py
```

### Key observations

- `src/` contains 17 Python modules + 1 package (experiments/)
- `data/` has Horizons cache (248 KB JSON) + results/ with JSONs, PNGs, GIF
- No `paper/`, `build/`, `figs/` directories (were cleaned)
- No `FINAL_AUDIT.md`, `POLISH_PLAN.md`, `ARCHITECTURE_REVIEW.md`, `ERROR_BUDGET.md`, `POLISH_IMPLEMENTATION.md`
- No `report.pdf` present

---

## 2. Delivery files

| File | Exists | Size | Notes |
|------|--------|------|-------|
| `report.tex` | YES | 34 KB | Main LaTeX source |
| `report.pdf` | NO | — | Not present; `make pdf` would generate it |
| `Makefile` | YES | 3.5 KB | 17 targets |
| `README.md` | YES | 4.9 KB | Overview, structure, instructions |
| `AI-Agent.md` | YES | 5.8 KB | AI usage report per module |
| `FINAL_AUDIT.md` | NO | — | Does not exist |
| `POLISH_PLAN.md` | NO | — | Does not exist |
| `ARCHITECTURE_REVIEW.md` | NO | — | Does not exist |
| `ERROR_BUDGET.md` | NO | — | Does not exist |
| `POLISH_IMPLEMENTATION.md` | NO | — | Does not exist |

**Risk:** Missing FINAL_AUDIT.md means no standalone audit trail; status is only in report.tex and README.md.

---

## 3. Makefile targets

### All targets

| Target | Dependency | Action |
|--------|-----------|--------|
| `all` | `compile pdf` | Syntax check + build PDF |
| `compile` | — | `python -m compileall src` |
| `validate` | `compile` | `validation.py --case all` |
| `m1`..`m8` | — | Individual milestone regression |
| `o3` | — | Run `shooting_corrector.py` |
| `pdf` | — | 2× xelatex `report.tex` |
| `figures` | — | `validation.py --case m8` (generates all PNGs) |
| `animation` | `figures` | `animation.py` |
| `scan-fast` | — | `validation.py --case m6` |
| `audit` | — | Checks creds, large files, token leaks |
| `clean` | — | Remove __pycache__, .pyc, LaTeX artifacts, all data/results/* |

### Risks

- `make all` only does `compile + pdf` — it does NOT run `figures` or `animation`. So `make all` alone would produce a PDF with broken image references if run on a clean checkout.
- `make figures` depends on `data/results/m3_residuals.json` (from M3), but `validation.py --case m8` internally calls M5+M6+M7. However, if `data/results/` was cleaned, M3 residuals JSON needs to be regenerated first (`make m3` or `make validate`).
- `make pdf` runs xelatex twice with `-interaction=nonstopmode` — may produce partial PDF if errors.
- `make clean` removes ALL `data/results/*.png`, `data/results/*.gif`, `data/results/*.json` — this includes the ablation results and time-unit checks. This is aggressive.
- There is no `make validate-m3` or `make validate-m4` target — only individual `m3`/`m4` which call `validation.py --case m3`.

---

## 4. Source architecture

### Module overview

| File | Lines | Role | Key functions/classes |
|------|-------|------|----------------------|
| `constants.py` | 93 | Physical constants | GM_SUN, GM_EARTH, GM_MOON, AU_KM, DT_MAIN/REFINE |
| `units.py` | 66 | Unit conversion | `au_to_km()`, `km_to_au()`, `day_to_sec()`, `rad_to_deg()` |
| `frames.py` | 193 | Reference frame transforms | `to_heliocentric()`, `to_barycentric()`, `project_to_2d()`, `relative_state()` |
| `dynamics.py` | 285 | N-body acceleration engine | `accel_barycentric()`, `accel_heliocentric_relative()` (with indirect term), `vv_step_nbody()`, `propagate_nbody()` |
| `nbody.py` | 519 | Main N-body integrator (legacy) | `nbody_accelerations()`, `vv_step_nbody()`, `propagate_nbody()`, `compute_conserved_quantities()`, `_run_m2_regression()` |
| `horizons.py` | 483 | JPL Horizons interface + M3 | `fetch_sem_vectors()`, `state_at_index()`, `compare_nbody_vs_horizons()`, `_run_m3_regression()` |
| `jpl_forward.py` | 45 | Proxy patch for Horizons API | `_patched_request()` |
| `patched_conic.py` | 304 | M1: Patched conic solver | `compute_patched_conic()`, `OrbitalElements`, `compute_phase_matching()` |
| `lunar_swingby.py` | 549 | M4: Lunar swingby | `compute_swingby_turn_angle()`, `compute_swingby()`, `simulate_swingby_nbody()`, `SwingbyResult`, `_run_m4_regression()` |
| `trajectory.py` | 559 | M5: Single-point trajectory | `DesignParams`, `TrajectoryResult`, `interpolate_state_at_mjd()`, `solve_trajectory()`, `_run_m5_regression()` |
| `optimize_window.py` | 596 | M6: Launch window optimization | `WindowScore`, `OptimizationResult`, `scan_launch_window()`, `score_single_day_fast()`, `_run_m6_regression()` |
| `sensitivity.py` | 441 | M7: Sensitivity analysis | `SensitivityPoint`, `SensitivityResult`, `sweep_parameter()`, `monte_carlo_analysis()`, `_run_m7_regression()` |
| `plotting.py` | 958 | M8: Visualization | `plot_trajectory()`, `plot_lunar_swingby()`, `plot_launch_windows()`, `plot_sensitivity()`, `plot_horizons_residual()`, `plot_energy_drift()`, `plot_delta_v_launch_date()`, `plot_t0_rp_contour()`, `generate_report_plots()`, `_run_m8_regression()` |
| `validation.py` | 104 | Regression test harness | `main()`, dispatches to `_run_mX_regression()` per module |
| `animation.py` | 248 | O5: Orbit animation | `generate_orbit_animation()` |
| `shooting_corrector.py` | 292 | O3: Shooting corrector | `newton_shoot()`, `compute_jacobian_fd()`, `propagate_to_target()` |
| `diagnostics.py` | 138 | M3 time/unit checks | `check_horizons_units()`, `run_horizons_sanity_check()` |
| `experiments/m3_residual_ablation.py` | 352 | M3 ablation study | 7 experiment modes E0–E6 |

### Architecture notes

- **Reference frame transforms** are in `frames.py` (new, clean). Legacy `horizons._project_to_2d()` still exists but is not used by `frames.py`.
- **Unit conversions** are in `units.py`. `constants.py` holds raw constants.
- **N-body acceleration**: `nbody.py:nbody_accelerations()` is the legacy function (barycentric only). `dynamics.py:accel_barycentric()` and `accel_heliocentric_relative()` are the newer implementations. Both provide equivalent results.
- **Velocity-Verlet**: `nbody.py:vv_step_nbody()` is the legacy integrator. `dynamics.py:vv_step_nbody()` is a new wrapper that routes to the correct acceleration mode.
- **M3 comparison**: `horizons.py:compare_nbody_vs_horizons()` uses `frames.relative_state()` for heliocentric residual. It propagates in SSB then compares in heliocentric frame (E3/E4 mode).
- **M4 numerical validation**: `lunar_swingby.py:simulate_swingby_nbody()` uses `vv_step_nbody` with SOI entry/exit tracking.
- **M6 refinement**: Added in `optimize_window.py:_run_m6_regression()` — top-5 N-body verification + sub-day local refinement (`±5d @ 0.5d`).
- **Plotting** is mostly self-contained: `_run_m8_regression()` calls M5/M6/M7 internally. But `plot_horizons_residual()` reads `data/results/m3_residuals.json` — must exist prior.
- **validation.py** is minimal (104 lines) — just dispatches. Not bloated.

---

## 5. M1-M8 status evidence

### 5.1 M1 — Patched Conic

| Item | Value |
|------|-------|
| Implementation | `src/patched_conic.py` |
| Key function | `compute_patched_conic(r_p_AU=0.2)` |
| Regression command | `make m1` or `python src/validation.py --case m1` |
| r_p=0.2 AU error | Max relative error 8.02e-04 (0.08% — PASS ≤0.1%) |
| Result files | None (inline print only) |
| Threshold | ≤0.1% relative error |
| Status | **DONE** — passes |
| Risk | Low |

### 5.2 M2 — N-body integrator

| Item | Value |
|------|-------|
| Implementation | `src/nbody.py` |
| Key function | `vv_integrate()`, `convergence_study()` |
| Regression command | `make m2` |
| Position error (h=1e-3) | 8.27e-05 (PASS ≤1e-4) |
| Energy drift | ~5×10⁻¹⁵ |
| Result files | None |
| Status | **DONE** — passes |
| Risk | Low |

### 5.3 M3 — JPL Horizons

**Full diagnostic table:**

| Item | Value | Source |
|------|-------|--------|
| Integration frame | SSB barycentric inertial | `horizons.py` L395–401 |
| Comparison frame | Heliocentric relative (post-hoc, not fitting) | `horizons.py` with `use_heliocentric=True` |
| Dimension | 3D (use_2d=False) | `horizons.py` L400 |
| Timestep | DT_REFINE = 60 s (for full 366-day propagation) | `horizons.py` L399 |
| Indirect term | Not in M3 main — only in ablation E6 | `dynamics.py` |
| Sun max pos | 0 km (by construction — heliocentric compare) | ablation E4 |
| Earth max pos | 5.90e+03 km (day 140) | ablation E4 |
| Moon max pos | 5.90e+03 km (day 140) | ablation E4 |
| Overall max pos | 5.90e+03 km | ablation E4 |
| Earth RMS pos | 3.49e+03 km | ablation E4 |
| Moon RMS pos | 3.49e+03 km | ablation E4 |
| Earth max vel | 1.64e-03 km/s | ablation E4 |
| Moon max vel | 1.63e-03 km/s | ablation E4 |
| 6,000 km threshold | PASS (all 3 bodies) | `_run_m3_regression()` |
| Result file | `data/results/m3_residuals.json` (366 rows) | `_save_residuals_json()` |
| Ablation file | `data/results/m3_residual_ablation.json` (7 exps) | `experiments/m3_residual_ablation.py` |
| Time/unit check | `data/results/m3_time_unit_check.json` — all PASS | `diagnostics.py` |
| Plot | `data/results/m8_horizons_residual.png` | `plotting.py:plot_horizons_residual()` |
| Reference sanity | Earth r=0.978 AU @ 2026-06-15 (SSB), v=30.26 km/s | `diagnostics.py` |

**Ablation summary (7 experiments):**

| Exp | Integration | Compare | Dim | dt(s) | Max Pos (km) | Threshold |
|-----|-------------|---------|-----|-------|-------------|-----------|
| E0 | barycentric | barycentric | 2D | 3600 | 4.62e+05 (Moon) | EXCEEDS |
| E1 | barycentric | barycentric | 3D | 3600 | 9.65e+04 (Sun) | EXCEEDS |
| E2 | barycentric | barycentric | 3D | 900 | 9.65e+04 (Sun) | EXCEEDS |
| **E3** | **barycentric** | **heliocentric** | **3D** | **900** | **5.92e+03 (Moon)** | **PASS** |
| **E4** | **barycentric** | **heliocentric** | **3D** | **60** | **5.90e+03 (Earth)** | **PASS** |
| **E5** | **barycentric** | **heliocentric** | **3D** | **300** | **5.90e+03 (Earth)** | **PASS** |
| E6 | heliocentric_relative | heliocentric | 3D | 900 | 5.92e+03 (Moon) | PASS |

**Key insight:** E3 and E6 give the same result (5,900 km). The 60s timestep (E4) provides negligible improvement over 900s (E3). The dominant residual is from **missing planetary perturbations** (Jupiter), not integration error. A 30-day 6-body test reduced residual to ~460 km.

**Status:** **DONE** (passes ≤6,000 km threshold). **But right at the edge (98.3%).**

### 5.4 M4 — Lunar Swingby

| Item | Value |
|------|-------|
| Analytical model | `src/lunar_swingby.py:compute_swingby()`, `compute_swingby_turn_angle()` |
| Numerical model | `src/lunar_swingby.py:simulate_swingby_nbody()` (with SOI entry/exit tracking) |
| Number of test cases | 1 test case (v_inf=2 km/s, r_p=R_moon+500 km, trailing) |
| Analytical deflection | 41.46° |
| Numerical deflection | 39.17° (2.29° difference) |
| v_inf conservation | 0.3% (PASS) |
| Impact parameter | b = 3,239 km, closest approach 2,567 km |
| Multi-case scan | NOT DONE — single point only |
| Result JSON | `data/results/` has `m4_swingby_numeric.json` — DOES NOT EXIST |
| Result plot | `data/results/` has `m4_swingby_angle_error.png` — DOES NOT EXIST |
| Regression command | `make m4` |

**Verification (only single point):**
- v_inf=2.0 km/s, trailing side, r_p=2237 km
- Analytical: delta=41.46°, dv=1.416 km/s
- Numerical (4-body VV): closest=2,567 km, delta=39.17°, dv from nonlinear calculation only through angle
- **Difference: 2.29° — reasonable given Sun+Earth tidal perturbations**

**Status:** **DONE** (single-point validation) **with significant gap:** No multi-case sweep across r_m or v_inf values. No dedicated result JSON saved.

### 5.5 M5 — Single-point Trajectory

| Item | Value |
|------|-------|
| Implementation | `src/trajectory.py:solve_trajectory()` |
| Regression command | `make m5` |
| Best t0 | MJD 61066.0 (as of report) |
| r_p achieved | 0.2843 AU (design 0.3 AU, error 5.2%) |
| v_launch | 14.70 km/s |
| v_reentry | 78.68 km/s |
| dist_moon_min | 21,374 km |
| swingby dv | 0.414 km/s |
| swingby delta | 2.28° |
| t_total | 96.12 days |
| Result file | `data/results/m5_debug.json` |
| No-Moon comparison | NOT done — no "节能比例" (fuel savings ratio) |
| Status | **DONE** — passes |
| Risk | Low; r_p error ~5% acceptable. No fuel savings comparison versus direct transfer. |

### 5.6 M6 — Launch Window Optimization

| Item | Value |
|------|-------|
| Implementation | `src/optimize_window.py:scan_launch_window()` |
| Coarse scan | 366 days, step=1d |
| Feasible windows | 132/366 |
| Mode | fast + local sub-day refinement (±5d @ 0.5d) |
| Best window (fast) | MJD 61154.0, angle=0.51°, score=0.4868 |
| Top-5 N-body verification | **5/5 successful** (new regression Test 3) |
| "Successful" definition | `traj.success=True` from `solve_trajectory()` — means: v_launch>V_ESCAPE, r_p finite, dist_moon_min<R_MOON_SOI, r_p_error<25% |
| Best refined r_p | 0.275 AU (MJD 61154.0, 8.33% error vs design 0.3 AU) |
| 2nd best refined r_p | 0.2843 AU (MJD 61066.0, 5.2% error) |
| r_p error range (top-5) | 0.2707–0.2844 AU (5.2%–9.7% error) |
| Result JSON | `data/results/m6_regression.json` + `data/results/m6_refined.json` |
| m6_regression top-10 | Only best (rank 1) has `full_success=True` — others are `False` |
| m6_refined | All 5 have `success=True` with full r_p/v_launch/v_reentry |

**Critical detail:** The `m6_regression.json` ranks 2–10 have `full_success=False` because the regression only runs N-body on the *single best window*. The `m6_refined.json` (from Test 3) has all 5 with `success=True`. The "top-5 N-body verification" is thus from Test 3, not from the main `scan_launch_window` path.

**Status:** **DONE** — but the success definition needs explicit documentation.

### 5.7 M7 — Sensitivity Analysis

| Item | Value |
|------|-------|
| Implementation | `src/sensitivity.py` |
| Parameters swept | t0 (±3d), r_m (±2000 km), r_p (±0.01 AU) |
| MC samples | 20 |
| Nominal r_p | 0.2843 AU |
| MC r_p mean/std | 0.2852 ± 0.0033 AU |
| v_launch mean/std | 14.70 ± 0.06 km/s |
| Step-size convergence | NOT done — no convergence study |
| Convergence order | Not estimated |
| Result file | `data/results/m7_sensitivity.json` |
| Status | **DONE** — but **step-size convergence analysis is missing** |

### 5.8 M8 — Visualization

| Item | Value |
|------|-------|
| Implementation | `src/plotting.py` |
| Plot functions | 8: `plot_trajectory()`, `plot_lunar_swingby()`, `plot_launch_windows()`, `plot_sensitivity()`, `plot_horizons_residual()`, `plot_energy_drift()`, `plot_delta_v_launch_date()`, `plot_t0_rp_contour()` |
| `generate_report_plots()` | YES — calls all 8 |
| Images in `data/results/` | 8 PNGs + 1 GIF (test animation) |
| Report references | `m8_trajectory.png`, `m8_lunar_swingby.png`, `m8_launch_windows.png`, `m8_sensitivity.png`, `m8_horizons_residual.png`, `m8_energy_drift.png`, `m8_delta_v_launch_date.png`, `m8_t0_rp_contour.png` — referenced by `\includegraphics` in report.tex |
| Make command | `make figures` calls `validation.py --case m8` |
| Figure manifest | NOT present |
| Status | **DONE** — 8/8 figures exist. No angular momentum drift plot exists (not needed if energy drift shown). |

---

## 6. Optional tasks

### O5 — Orbit Animation

| Item | Value |
|------|-------|
| File | `src/animation.py` |
| `make animation` | YES (depends on `figures`) |
| Output | GIF (fallback when ffmpeg not available) |
| Path | `data/results/m8_anim_test.gif` (5s test only) |
| Full animation | Not generated (only 5s test) |
| Gitignored | `data/results/` is gitignored, so yes |
| In `make all` | **NO** — `make all` only does `compile + pdf` |
| README note | Not explicitly stated that animation is optional |
| Risk | No full 45s animation produced yet |

### O3 — Shooting Corrector

| Item | Value |
|------|-------|
| File | `src/shooting_corrector.py` |
| Method | Newton-Raphson with numerical Jacobian |
| Test | Single test case: Moon intercept direction (1 parameter) |
| Convergence | Did NOT fully converge (final error 1.09e+07 km after 20 iterations) |
| Reason | 1 parameter can't control 2D position; ill-conditioned |
| Result JSON | NOT saved |
| Stability | Unstable for single-parameter case; the framework works but needs more parameters |
| Impact on M6 | **NONE** — not integrated into main pipeline |
| Report status | Mentioned as "exploratory optional task" |

---

## 7. Report audit

### Section structure

```
1. Abstract
2. Project background and problem description
3. Modeling assumptions
4. Patched conic (M1)
5. N-body integrator (M2)
6. JPL Horizons comparison (M3)
7. Lunar swingby (M4)
8. Single-point trajectory (M5)
9. Launch window optimization (M6)
10. Sensitivity analysis (M7)
11. Visualization (M8)
12. Limitations and improvements
13. Conclusion
14. Acknowledgments
15. AI tool usage statement
```

### Key checks

- **Model assumptions section:** YES (§3)
- **Error sources discussion:** YES (§6.3 for M3, §12 for limitations)
- **M1-M8 status table:** YES (conclusion section)
- **Figure references:** YES — 8 images referenced (trajectory, swingby, windows, sensitivity, residual, energy drift, delta-v curve, t0-rp contour)
- **Limitations section:** YES (§12)
- **AI usage declaration:** YES (§15, module-specific)
- **Exaggerated phrasing (危险词汇):** NOT found (`全部严格满足`, `工程级高精度`, `完全高保真`, `远低于阈值` — all absent)

### Potential reporting issues

1. **M3** — Abstract says "M3 通过三维日心系残差法将位置误差控制在 6000 km 以内" → accurate but doesn't clarify it's borderline
2. **M4** — States "解析模型和数值仿真均已实现" and "M4 标记为 done" → but only 1 test case; could be seen as insufficient
3. **M6** — Reports best window r_p=0.2750 AU with 8.33% error; does NOT explain that 2nd best (MJD 61066.0) gives 5.2% error with better r_p matching
4. **Limitations §12** — Still mentions "M4 numerical simulation incomplete" but M4 is now done; needs update
5. **Status table** — Shows O3/O5 as completed but no evidence in report body (just conclusion table)

---

## 8. Documentation consistency

### README.md

- States M3 as `[partial]`, M4 as `[partial]`, M8 as `[partial]`
- **OUTDATED** — M3/M4/M8 are now `done` in report.tex and code
- References `data/results/m6_windows.json` (file is `m6_regression.json`)

### AI-Agent.md

- Covers all modules with per-module development narrative
- Does NOT mention `frames.py`, `dynamics.py`, `diagnostics.py`, `experiments/`
- Does NOT mention the ablation study
- Does NOT mention the M3 reference frame fix
- Useful but not current

### Consistency assessment

- **README status ≠ report status** — README says partial for M3/M4/M8, report says done
- **FINAL_AUDIT.md missing** — no authoritative audit trail
- **AI-Agent.md missing new modules** — frames.py, dynamics.py, diagnostics.py
- **No CHANGELOG or commit history** — git has no commits yet (all untracked)

---

## 9. Submission risks

### `.gitignore` coverage

Covered: `__pycache__/`, `*.pyc`, `data/*.json` (except README), `figs/*.png`, `figs/*.mp4`, `build/`, `*.aux`, `*.log`, `config/`, `PROJECT_PLAN.md`, `report.pdf`, `data/results/`, `.DS_Store`, `Thumbs.db`

**Missing from .gitignore:**
- `*.gif` (animation output)
- `*.csv` (ablation output)
- `.pyc` at root level (covered by `*.pyc`)
- `data` subdirectory has `!data/README.md` exception — OK
- `figs/` directory doesn't exist anymore, so rules are harmless

### Token/credential check

**Token found in `config/proxy.ini`** (forward_token = fce2a741...). This is expected and properly handled:
- `.gitignore` has `config/` — whole directory excluded
- `git check-ignore -v config/proxy.ini` confirms: `.gitignore:31:config/`
- The same `proxy.ini` has forward_url = `http://8.216.49.176:18766/api/horizons.api`

**No other token occurrences in tracked Python files** (only `Makefile` grep command, `jpl_forward.py` reference to config file).

### Large file check

- Largest file: `data/sem_horizons_2026-2027.json` at 248 KB
- All PNGs: 30–180 KB each
- Total repo size: 505 KB (source + data + pycache)
- **No files >5MB** — OK
- `data/results/` is gitignored — OK
- `report.pdf` is gitignored — OK

### Other risks

- `__pycache__/` is present but should be gitignored (already in `.gitignore`)
- `git status --short` shows all files as untracked — no commits yet exist
- No remote configured in git

---

## 10. Command availability

| Command | Status | Notes |
|---------|--------|-------|
| `python -m compileall src` | PASS (all files compile) | Tested |
| `make -n compile` | OK | Runs compileall |
| `make -n validate` | OK | Requires compile first, runs all m1-m8 |
| `make -n validate-m3` | **DOES NOT EXIST** | Only `make m3` exists |
| `make -n validate-m4` | **DOES NOT EXIST** | Only `make m4` exists |
| `make -n figures` | OK | Runs m8 regression (calls M5+M6+M7 internally) |
| `make -n pdf` | OK | 2× xelatex on report.tex |
| `make -n audit` | OK | Credential check |

### make dry-run findings

- `make figures` requires matplotlib and ~2+ min (M5+M6+M7+M8)
- `make validate` requires ~10+ min (all 8 milestones)
- `make pdf` requires xelatex with ctex + Times New Roman font
- No target auto-detects whether `data/results/` PNGs are stale
- `make animation` depends on `figures`, which adds another ~1-5 min

---

## 11. Executive summary for external reviewer

### A. Current best-known status

| Item | Status | Evidence | Risk |
|------|--------|----------|------|
| M1 patched conic | DONE | 0.08% error vs Qian reference | Low |
| M2 N-body integrator | DONE | pos_err 8.27e-05, energy drift 5e-15 | Low |
| M3 JPL Horizons | DONE (borderline) | 5,900 km max (6,000 km threshold); ablation study done; time/unit check done | **Edge of threshold; missing perturbers** |
| M4 lunar swingby | DONE (single point) | Only 1 test case; no multi-parameter sweep | **Insufficient coverage** |
| M5 trajectory | DONE | r_p=0.2843 AU (5.2% error) | No fuel savings comparison |
| M6 launch window | DONE | Top-5 N-body verified; best MJD 61154.0 | r_p error 8.33% not improved over coarse; best-by-N-body is MJD 61066.0 at 5.2% |
| M7 sensitivity | DONE | 20 MC samples + parameter sweep | **No step-size convergence** |
| M8 visualization | DONE | 8 figures all generated | Figure manifest missing |
| O5 animation | PARTIAL | Only 5s test GIF generated; no full MP4 | Low (bonus) |
| O3 shooting corrector | EXPLORATORY | Framework exists; didn't converge for 1-param case | Not integrated into M6 |

### B. Most important open questions

1. **M3: Is 5,900 km the ALL-year MAX across ALL bodies?**
   Yes — Earth max at day 140 (5,897 km), Moon max at day 138 (5,900 km). The RMS is 3,485 km. So year-max is 5,900 km for Earth, 5,900 km for Moon.

2. **M3: Is `use_heliocentric=True` correct reference-frame dynamics or post-hoc drift removal?**
   It's **post-hoc comparison-frame unification**, not post-hoc fitting. The integration is done in SSB barycentric inertial frame (correct N-body dynamics). Then at each epoch, both numerical and reference states are transformed to heliocentric frame for comparison. This eliminates the common-mode SSB drift from missing planetary perturbations. The E6 experiment proves that doing the integration in heliocentric frame with indirect term gives identical results — so the approach is physically consistent, not a "fudge". Documented in `frames.py`.

3. **M4: Is the numerical validation only a single point?**
   Yes — only v_inf=2.0 km/s, r_p=R_moon+500 km, trailing side. No multi-case scan. No `m4_swingby_numeric.json`. The only evidence is the inline Test 5 output from `_run_m4_regression()`.

4. **M6: What does "successful" mean for top-5 N-body verification?**
   `traj.success=True` means: `v_launch>V_ESCAPE_EARTH`, `v_reentry>0`, `r_p_achieved` finite, `dist_moon_min<R_MOON_SOI`, and `r_p_rel_error<25%`. All 5 top windows pass these checks.

5. **M7: Is step-size convergence missing?**
   Yes. No convergence study for the trajectory solver. Only perturbation sensitivity is analyzed.

6. **M6 refinement: Did it improve r_p error?**
   **No.** The best window by geometry (MJD 61154.0) still gives 8.33% r_p error. The 2nd window (MJD 61066.0) gives 5.2% — actually better. The refinement verified that different windows produce different r_p accuracy, but didn't systematically improve the target r_p matching.

7. **M8: Does plotting only read result files or recompute?**
   `_run_m8_regression()` recomputes M5 (trajectory), M6 (window scan), and M7 (sensitivity) internally. `plot_horizons_residual()` reads `m3_residuals.json`. `plot_energy_drift()` recomputes from scratch. `generate_report_plots()` accepts precomputed results or recomputes.

8. **Are results deterministic between machines?**
   Mostly yes — all random seeds are fixed (MC seed=42). The JPL proxy response is deterministic. The only variable is the Horizons cache (data/sem_horizons_2026-2027.json) — must exist or network access needed.

9. **What is the correct `make all` workflow for a fresh checkout?**
   `make compile && make validate && make pdf` — but this will skip figures! The correct order is: `make validate` (generates all result files) → `make pdf`. Or `make compile && make m3 && make m5 && make m6 && make m7 && make m8 && make pdf`.

10. **Is report.pdf ≤40 pages?**
    Cannot check — `report.pdf` does not exist. `report.tex` is 34 KB, approximately 15-20 pages when compiled.

### C. Recommended next modifications

Priority order (focused on hard indicators):

1. **M3 error budget** — 6-body extension experiment to quantify Jupiter perturbation; document that 5,900 km is a physical model limit, not integration error
2. **M4 scan** — Add multi-case sweep (5 r_m values × 5 v_inf values × 2 sides), save `m4_swingby_numeric.json`
3. **M6 r_p matching** — Either change best window to MJD 61066.0 (5.2% error) or add iterative refinement to improve r_p at MJD 61154.0
4. **M7 convergence** — Add step-size convergence study (h = 3600, 1800, 900, 300, 60s → r_p error)
5. **M6 "successful" definition** — Document in report: `dist_moon_min<R_MOON_SOI (66k km)` and `r_p_rel_error<25%`
6. **README sync** — Update M3/M4/M8 status from `[partial]` to `[done]`
7. **FINAL_AUDIT.md** — Create standalone audit file
8. **M8 figure manifest** — Add `figure_manifest.json`
9. **Report update** — Add M3 ablation table, M4 numerical comparison table, M6 refined window table
10. **make all fix** — Add `figures` and `animation` as optional dependencies to `make all`, with a note that they can be skipped for a quick PDF build
