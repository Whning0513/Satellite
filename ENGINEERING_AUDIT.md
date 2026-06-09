# Engineering & Code Implementation Audit

Generated: 2026-06-10
Purpose: Check code quality, entrypoint consistency, unit/frame safety, legacy classification.

## Entrypoint Map

### Main pipeline (make all / make validate)
| target | script | purpose | speed | deterministic |
|--------|--------|---------|-------|---------------|
| `make m1` | `validation.py --case m1` | patched conic regression | fast | yes |
| `make m2` | `validation.py --case m2` | N-body integrator regression | fast | yes |
| `make m3` | `validation.py --case m3` | Horizons comparison | medium | yes |
| `make m4` | `validation.py --case m4` | lunar swingby regression | fast | yes |
| `make m5` | `validation.py --case m5` | trajectory solver | medium | yes |
| `make m6` | `validation.py --case m6` | window scan | medium | yes |
| `make m7` | `validation.py --case m7` | sensitivity | medium | yes |
| `make m8` | `validation.py --case m8` | visualization | medium | yes |
| `make m5-fair` | `experiments/m5_fair_no_lunar_baseline.py` | no-lunar baseline | fast | yes |
| `make m5-lambert` | `experiments/m5_no_lunar_lambert_baseline.py` | Lambert baseline | medium | yes |
| `make figures` | `validation.py --case m8` | 8 PNGs | medium | yes |
| `make pdf` | xelatex report.tex | PDF | fast | yes |

### Optional / bonus (not in make all)
| target | script | purpose | speed | deterministic |
|--------|--------|---------|-------|---------------|
| `make o3` | `experiments/o3_differential_corrector.py` | O3 angle/scale corrector | fast | yes |
| `make o3plus` | `experiments/o3plus_vector_differential_corrector.py` | O3+ vector corrector | medium | yes |
| `make o4-mga` | `experiments/o4_multi_gravity_assist.py` | O4 chain search | medium | yes |
| `make o4plus` | `experiments/o4plus_powered_mga_optimizer.py` | O4+ powered MGA | medium | yes |
| `make o7-parallel` | `experiments/o7_parallel_scan.py` | ProcessPool benchmark | slow | yes |
| `make o7-surrogate` | `experiments/o7_surrogate_prefilter.py` | Ridge surrogate | slow | yes |
| `make animation` | `animation.py` | orbit animation MP4 | slow (needs ffmpeg) | partial |
| `make o1-3d` | `experiments/o1_3d_comparison.py` | 3D diagnostic | fast | yes |
| `make o2-gr` | `experiments/o2_relativity.py` | GR diagnostic | fast | yes |
| `make o4-ephem` | `experiments/o4_ephemeris_extend.py` | Venus ephemeris | fast (cache) | yes |

### Diagnostic / supporting (not in bonus-all)
| target | script | purpose |
|--------|--------|---------|
| `make delta-v-audit` | `delta_v_budget.py --self-test` | Δv budget classification |
| `make m5-global-baseline` | `experiments/m5_global_no_lunar_baseline.py` | broader no-lunar search |
| `make m6-pareto` | `experiments/m6_pareto_window_diagnostic.py` | Pareto trade-off |
| `make figure-manifest` | `experiments/generate_figure_manifest.py` | figure inventory |
| `make scan-fast` | `validation.py --case m6` | fast window scan |

### Slow targets (≥60s)
- `make all`: ~2-3 min (includes m3 + figures + m5-fair/m5-lambert + pdf)
- `make o7-parallel`: ~3-5 min (serial N-body solves for 55 MJDs)
- `make o7-surrogate`: ~5 min (70 sample N-body solves)
- `make o3plus`: ~2-5 min (6-15 multi-start runs)
- `make animation`: depends on ffmpeg

### Orphan / no Makefile entry scripts
| script | has __main__ | has make target | assessment |
|--------|-------------|----------------|------------|
| `diagnostics.py` | yes | no | M3 time/unit check, one-off |
| `horizons.py` | yes | no | cache fetch, called as lib |
| `nbody.py` | yes | no | called as lib; __main__ is test |
| `patched_conic.py` | yes | no | called as lib; __main__ is test |
| `trajectory.py` | yes | no | called as lib; __main__ is test |
| `lunar_swingby.py` | yes | no | called as lib; __main__ is test |
| `sensitivity.py` | yes | no | called as lib; __main__ is test |
| `plotting.py` | yes | no | called via validation.py |
| `optimize_window.py` | yes | via validation m6 | called as lib + __main__ test |
| `shooting_corrector.py` | yes | replaced by o3 | legacy, no longer referenced |
| `interactive_demo.py` | yes | o6-interactive | GUI, needs display |

## Legacy scripts

| script | lines | status | notes |
|--------|-------|--------|-------|
| `aux_results.py` | 249 | legacy/historical | Handles M6 dv_total aux rankings. Kept for reference. |
| `m5_m6_dv_audit.py` | 232 | legacy/historical | Older dv audit. Replaced by DELTA_V_BUDGET_AUDIT. |
| `m5_no_lunar_comparison.py` | 139 | legacy/historical | Earlier no-lunar comparison. Replaced by m5-fair + m5-lambert. |
| `m6_dv_audit.py` | 241 | legacy/historical | Earlier dv audit. Superseded. |
| `shooting_corrector.py` | 292 | legacy (replaced) | Old 1-param O3, replaced by o3_differential_corrector.py |

## Unit / Frame Audit

### Constants
| constant | file | value | notes |
|----------|------|-------|-------|
| `GM_SUN` | `constants.py:17` | 1.32712440041279419e11 km³/s² | JPL ASTRODYN |
| `GM_EARTH` | `constants.py:20` | 398600.435507 km³/s² | JPL ASTRODYN |
| `GM_MOON` | `constants.py:23` | 4902.800118 km³/s² | JPL ASTRODYN |
| `GM_VENUS` | `constants.py:101` | 324858.592000 km³/s² | JPL ASTRODYN |
| `AU_KM` | `constants.py:34` | 149597870.7 km | Standard IAU |
| `R_EARTH` | `constants.py:41` | 6371.0 km | Standard |
| `R_MOON` | `constants.py:42` | 1737.4 km | Standard |
| `V_EARTH_ORBIT` | `constants.py:49` | 29.80 km/s | From Qian textbook |
| `V_ESCAPE_EARTH` | `constants.py:50` | 11.18 km/s | From Qian textbook |
| `DT_MAIN` | `constants.py:66` | 3600.0 s | Velocity-Verlet main step |
| `DT_REFINE` | `constants.py:67` | 60.0 s | Velocity-Verlet refine step |

### Coordinate frame boundary
- **Earth->Moon leg (O4/O4+)**: Geocentric relative positions + GM_EARTH (correct)
- **Moon->Venus / Venus->Earth legs (O4/O4+)**: Heliocentric SSB positions + GM_SUN (correct)
- **M3 residuals**: SSB propagate, then transform to heliocentric for comparison (correct — verified by ablation E3 vs E6)
- **M5 trajectory S1–S6**: SSB N-body propagation throughout
- **Patched conic (M1)**: Heliocentric 2-body for interplanetary leg, Earth 2-body for surface-to-parking

### v_inf / Δv definitions
- `v_inf_earth` (departure): Earth-relative hyperbolic excess, defined by C3 = v_inf²
- `departure_vinf`: Same as above, used in O4/O4+ as launch cost proxy
- `v_rel_earth` (return): |rocket_heliocentric - earth_heliocentric| — NOT a fuel cost directly
- `v_reentry`: sqrt(v_rel_earth² + V_esc²) — used in M6 dv_total proxy
- `dv_total` (M6): v_launch + v_reentry, NOT comparable to Qian symmetric total Δv
- `dv_total` (O4+): dep_vinf + moon_pow + venus_pow + reentry_brake, a simplified MGA budget

**Risk**: M6 dv_total definition differs from Qian's total Δv. Already documented in DELTA_V_BUDGET_AUDIT.md.

### No unit/frame bugs found
All GM constants are km³/s², all positions are km, all velocities are km/s. Time uses MJD for epochs and seconds for propagation. Frame mixing risk in O4/O4+ was audited and confirmed consistent (geocentric for Earth→Moon, heliocentric for interplanetary legs).

## Safety Scan

| pattern | file | risk | action taken |
|---------|------|------|-------------|
| `subprocess.run(['ffmpeg'...])` | `animation.py:235` | low | Only used for MP4 encoding, safe fallback to GIF |
| `open(path, "w")` pattern | many files | low | All use `os.makedirs` or explicit encoding; no destructive overwrites |
| Token in `config/proxy.ini` | config (gitignored) | low | Properly gitignored; audit checks for leaks |
| `shutil.rmtree` | none found | — | — |
| `os.system` or `shell=True` | none found | — | — |

## Conclusion

The engineering implementation is consistent: all constants use km-s units, frame boundaries are well-defined, and legacy scripts are clearly separable from active ones. No bugs affecting scientific conclusions were found. The main risk (M6 dv_total definition mismatch) is already documented. The codebase is ready for submission.
