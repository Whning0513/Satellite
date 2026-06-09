# Requirement-to-Code Traceability Audit

Generated: 2026-06-09
Purpose: Final audit of M1–M8 requirements against code, Makefile, and report.

## Basic requirement judgment

- M1–M8 complete: **Yes**
- pass count: **6** (M1, M2, M4, M6, M7, M8)
- pass-with-caveat count: **2** (M3 borderline threshold, M5 no saving ratio)
- fail/missing count: **0**
- main caveats: M3 passes 6,000 km but at 5,900 km (98.3%); M5 saving ratio not reported because no fair no-lunar candidate satisfies both perihelion and return-v_inf constraints

---

## Requirement traceability

| ID | Status | Implementation | Make target | Evidence | Caveat |
|----|--------|---------------|-------------|----------|--------|
| M1 | **pass** | `src/patched_conic.py` — `compute_patched_conic()`, `OrbitalElements` | `make m1` → `validation.py --case m1` | error vs Qian rp=0.2 AU: 0.08% (< 0.1%). Report §4. Numerical results table. | None |
| M2 | **pass** | `src/nbody.py` — `vv_step_nbody()`, `propagate_nbody()`, `nbody_accelerations()` | `make m2` → `validation.py --case m2` | 2-body circular test: pos_err 8.27e-5 (< 1e-4). Energy drift < 5e-15. Report §5. M2 convergence table. | None |
| M3 | **pass (borderline)** | `src/horizons.py` — `fetch_sem_vectors()`, `compare_nbody_vs_horizons()`. Cache: `data/sem_horizons_2026-2027.json` | `make m3` → `validation.py --case m3` | Max residual 5,900 km ≤ 6,000 km. Heliocentric compare method. 3D propagation. Report §6. Residual table + error budget. | Passes at 98.3% of threshold. Dominant residual from missing Jupiter perturbations, not numerical error. |
| M4 | **pass** | `src/lunar_swingby.py` — `compute_swingby()`, `compute_swingby_turn_angle()`, `simulate_swingby_nbody()`. Scan: `experiments/m4_swingby_scan.py` | `make m4` → `validation.py --case m4` | Analytic vs numerical: 2.29 deg difference at v_inf=2 km/s. 60-case grid scan, median error 0.04 deg. Report §7. Turn angle table + scan summary. | Local moon-centric 2-body validation, not mission-level N-body swingby. |
| M5 | **pass-with-caveat** | `src/trajectory.py` — `solve_trajectory()`, `DesignParams`, `TrajectoryResult`. Baselines: `experiments/m5_fair_no_lunar_baseline.py`, `experiments/m5_no_lunar_lambert_baseline.py` | `make m5` / `make m5-fair` / `make m5-lambert` | rp=0.2843 AU (5.2% error), v_launch=14.70 km/s. Two no-lunar baselines: SOI-exit tangent + Earth-to-Earth Lambert. Report §8. M5 result table + Pareto plot. | **No saving ratio reported** — no fair no-lunar candidate satisfies both perihelion match and return v_inf ≤ 15 km/s at tested dates. Old -430% result discarded. |
| M6 | **pass** | `src/optimize_window.py` — `scan_launch_window()`, `score_single_day_fast()`. Sub-day refinement. | `make m6` → `validation.py --case m6` | 366 days scanned, 132 feasible. Best MJD 61154.0. Top-5 N-body verified. Report §9. Window table + contour plot. | r_p error 5-10% from geometric scoring. Best Δv and best balanced window differ. |
| M7 | **pass** | `src/sensitivity.py` — `sweep_parameter()`, `monte_carlo_analysis()`. Convergence: `experiments/m7_stepsize_convergence.py` | `make m7` → `validation.py --case m7` | 3-parameter sweep (t0, rm, rp) + 20-sample MC + 4-level dt convergence (3600/1800/900/450s). Report §10. Sensitivity table + step convergence table. | 20 MC samples insufficient for statistical significance. Convergence order not well-defined due to non-smooth r_p response. |
| M8 | **pass** | `src/plotting.py` — 8 plot functions. `generate_report_plots()` aggregates all. | `make figures` → `validation.py --case m8` | 8 static PNGs: trajectory, lunar swingby, launch windows, sensitivity, Horizons residual, energy drift, Δv-launch-date, t0-rp contour. Report §11. All report figure references resolved. `figure_manifest.json`. | None. Figure generation is self-contained (M5/M6/M7 results recomputed internally). |

---

## Optional task status check

| ID | Status | Caveat |
|----|--------|--------|
| O1 | diagnostic | 3D vs 2D diff ~12,600 km. Does not replace 2D main result. |
| O2 | done | a_GR/a_N = 6.7e-8, Δr_p < 1 km. Negligible effect. |
| O3/O3+ | done-with-caveat / done | **O3**: target-leak bug caught by audit. After fix ~4x (918k→248k km). No-scipy framework. **O3+**: vector LM corrector, 74.59x, final miss 66,210 km < 100,000 km threshold. |
| O4 | frozen exploratory | Frozen at commit `18fa865`. Pure-assist Lambert-chain search. 98 candidates, 0 feasible-ish. |
| O4+ | done (optimizer) | Independent from O4. Powered flyby residuals allowed. 142 Lambert candidates, 0 feasible_powered. Confirms O4 conclusion. No "solar propulsion" wording. |
| O5 | done | 45s MP4/GIF orbit animation. MP4 not in git. |
| O6 | done | Interactive demo (Tkinter/Matplotlib GUI). Requires local display. |
| O7 | done | ThreadPool negative (0.56x). ProcessPool mean 3.78x. Ridge surrogate R²=0.8956 but Top-15 recall 33.3% — diagnostic only. |

---

## Validation

- compile: ✅ `python -m compileall src` passes
- make all: ✅ compile → m3 → figures → m5-fair → m5-lambert → pdf (32 pages)
- make audit: ✅ all security, figure, M5-file, size checks pass
- make pdf: ✅ 32 pages
- PDF pages: 32 (< 40 ✅)
- dangerous wording check: ✅ No "solar propulsion", "fully optimized", "guaranteed". `3.87e9` only in invalidated context (FINAL_AUDIT.md, AI-Agent.md). `saving ratio` only in "not reported" context.
- token check: ✅ config/ gitignored, no tracked leaks
- git status: ✅ clean after commit
- commit hash: `f84bc07` (latest), with tag `final-submission-all-bonus`

---

## Final conclusion

**All M1–M8 basic requirements are complete.** M1, M2, M4, M6, M7, M8 pass without major caveats. M3 passes the 6,000 km threshold but is close (5,900 km, 98.3%); the dominant residual source is missing planetary perturbations, not numerical error — this is honestly documented. M5 baseline search is thorough (two independent no-lunar baselines + Lambert search) but no saving ratio is reported because no fair no-lunar candidate simultaneously satisfies perihelion and return-v_inf constraints — this is explicitly stated in the report. All optional tasks (O1–O7, O4+) are implemented or frozen with honest status labels. The project is ready for clean-room submission.
