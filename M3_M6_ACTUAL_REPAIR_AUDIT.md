# M3 / M6 Actual Repair Audit

## Status Summary

| 项目 | M3 | M6 |
|------|-----|-----|
| Previous method | Ratio estimate (5900 × 460 / 2500) | Geometric proxy (score = 15 + 0.3 × moon_dist / 384400) |
| New method | **Fidelity hierarchy** (3-body / 5-body / full planetary) | Actual solve_trajectory for top 10 dates |
| Actual propagation | ✅ All three models, same year/sampling | ✅ Full N-body trajectory per candidate |
| 3-body residual | **5912 km** (baseline, passes 6000 km) | — |
| 5-body residual | **1401 km** (76.3% improvement) | — |
| Full planetary residual | **126 km** (97.9% improvement) | — |
| Strict feasible candidates | — | **0 / 10** (all return_vinf > 53 km/s) |

---

## M3 model hierarchy (fidelity chain)

M3 is now represented as a **fidelity hierarchy**, not a single replacement result:

| Level | Model | Bodies | Max residual | Improvement vs 3-body | Pass threshold | Role |
|-------|-------|--------|------------:|---------------------:|:------------:|------|
| 1 | SEM_3body | Sun, Earth, Moon | 5912 km | baseline | ✅ | Minimum baseline |
| 2 | SEM_Jupiter_Venus_5body | Sun, Earth, Moon, Jupiter, Venus | 1401 km | 76.3% | ✅ | Higher fidelity with perturbations |
| 3 | SEM_full_planetary | Sun + 8 planets + Moon | **126 km** | **97.9%** | ✅ | Full solar-system diagnostic |

- **SEM_3body** remains the minimal baseline model and passes the 6000 km threshold.
- **SEM_Jupiter_Venus_5body** shows that Jupiter+Venus perturbations explain most (~76%) of the 3-body residual.
- **SEM_full_planetary** (10-body) reduces the residual to just 126 km, confirming that planetary perturbations account for essentially all remaining error in the 3-body model.
- All three models use actual N-body propagation (not estimates), the same 1-year sampling, dt=900s, and the same M3 residual definition (heliocentric relative error).
- This hierarchy replaces the earlier "ratio estimate" (5900 × 460 / 2500 ≈ 1086 km) which was not an actual propagation result.

---

## M6 actual repair

- **proxy removed:** ✅ — old geometric proxy replaced with actual solve_trajectory
- **candidates searched:** 10 top M6 scores, each solved with full N-body
- **DSM allowed:** Yes (Mode B uses existing M5 DSM search at matching dates)
- **feasible low-return found:** **0 / 10**
- **best feasible/near-feasible:** MJD 61183, return_vinf = 53.97 km/s (still >> 15)
- **DSM-assist available for:** 4/10 dates (61154, 61066, 61125, 61213)
- **DSM-assisted return_vinf:** 5.97–13.78 km/s (all < 15, with lower total dv)
- **status:** `no_feasible_candidate_found`
- **verdict:** No M6 lunar-assisted candidate achieves return_vinf ≤ 15 km/s. The lunar flyby naturally produces very high return speeds (53–81 km/s). DSM-assisted alternatives exist (from M5), but those are no-lunar searches and not M6 candidates.

---

## Validation

| Check | Result |
|-------|--------|
| compile | ✅ |
| repair-m3-actual (hierarchy) | ✅ (60s — includes full planetary + data fetch) |
| repair-m6-actual | ✅ (instant — reuses cached trajectories) |
| schema-check | ✅ (0 errors) |
| make audit | ✅ |
| git status | Pending commit |
