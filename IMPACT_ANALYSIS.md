# Impact Analysis: M5/M6 Lunar Return Event Invalidation

## Status

**INVALIDATED.** The M5/M6 lunar-assisted trajectories never reach Earth return.
The S5 heliocentric coast propagates half a period (≈ 96 days) and stops at
perihelion (~0.28 AU, ~164 M km from Earth).  All return quantities computed
from this end state (return_vinf, v_reentry, return_braking, total_dv_proxy,
saving ratio) are heliocentric velocity differences at different spatial
positions, NOT Earth-return quantities.

## What was invalidated

| Quantity | Old value | Reason for invalidation |
|----------|----------:|------------------------|
| M5 lunar return_vinf | 77.88 km/s | Measured at perihelion (~0.28 AU), not Earth (~1.0 AU). Spacecraft 164 M km from Earth. |
| M5 lunar v_reentry | 78.68 km/s | Derived from invalid return_vinf. |
| M5 lunar return_braking | 62.88 km/s | Derived from invalid return_vinf. |
| M5 lunar total_dv_proxy | 73.00 km/s | Uses return_braking from invalid return_vinf. |
| M5 fixed-date saving ratio | −187.3% | Compares perihelion velocity diff to actual Earth return from DSM. |
| M5 budget sensitivity (all modes) | All negative | Uses invalid lunar return_vinf. |
| M6 return_vinf claims | 53–98 km/s | All measured at perihelion, not Earth. |

## What remains valid

| Result | Classification | Status |
|--------|--------------|--------|
| DSM no-lunar baseline | ACTUAL_RESULT | Valid. Lambert arrives at Earth (r ≈ 1.0 AU). Return_vinf = 5.97 km/s is real. |
| M3 model hierarchy | ACTUAL_RESULT | Valid. No data leakage. |
| M4 swingby scan | ACTUAL_RESULT | Valid. 60-case, median error 0.026°. |
| M7 MC sensitivity | ACTUAL_RESULT | Valid. Independent of return. |
| O3+ corrector | ACTUAL_RESULT | Position-shooting only, caveated. |
| O4+ MGA | ACTUAL_RESULT | 0 feasible, caveated as infeasible. |
| event_semantics guard | BUG_FIXED | Prevents computing return_vinf when not at Earth. |

## M5 lunar+return-DSM (separate mission class)

A completed mission class was constructed by adding a Lambert return DSM
from the perihelion+45d state to Earth.  This is NOT equivalent to a pure
lunar free return.

| Quantity | Value |
|----------|------|
| Return DSM | 26.75 km/s |
| Arrival return_vinf | 6.18 km/s |
| Completed total_dv_proxy | 36.87 km/s |
| Mission class | lunar_plus_return_dsm |
| Reference ratio vs DSM no-lunar | −45.1% (completed lunar still worse) |

This comparison is **DIAGNOSTIC only**.  It cannot replace the pure lunar
saving ratio because the pure lunar free return does not exist under the
current trajectory design.

## Action items

1. **Do NOT modify report.tex** in this cycle.
2. All future references to M5/M6 lunar return must specify whether they
   refer to pure lunar (missing), lunar+return-DSM (completed, powered), or
   no-lunar DSM (valid independent baseline).
3. The −187.3% figure must never be cited as a formal saving ratio.
