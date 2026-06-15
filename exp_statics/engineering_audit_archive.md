# Engineering Audit Archive

This file consolidates the technical audit and evidence notes that used to live as separate root-level Markdown files.

## Source documents absorbed

- `ENGINEERING_AUDIT.md`
- `ENGINEERING_REPAIR_AUDIT.md`
- `EXTERNAL_BENCHMARK_COMPARISON.md`
- `IMPACT_ANALYSIS.md`
- `M3_M6_ACTUAL_REPAIR_AUDIT.md`
- `REPAIR_CLAIM_VERIFICATION.md`
- `DELTA_V_BUDGET_AUDIT.md`

## 1. Engineering audit summary

The project implementation was audited across the core Makefile targets and supporting scripts.

### Core pipeline targets

| Target | Purpose | Status |
|---|---|---|
| `make m1` | patched conic regression | pass |
| `make m2` | N-body regression | pass |
| `make m3` | Horizons comparison | pass |
| `make m4` | lunar swingby regression | pass |
| `make m5` | trajectory solver | pass with caveat |
| `make m6` | window scan | pass |
| `make m7` | sensitivity | pass |
| `make m8` | visualization | pass |

### Optional technical targets

| Target | Purpose | Status |
|---|---|---|
| `make o3` / `make o3plus` | differential correctors | done |
| `make o4-mga` / `make o4plus` | MGA explorations | exploratory / done |
| `make o7-parallel` / `make o7-surrogate` | performance and surrogate experiments | done |
| `make animation` | orbit animation | done |

## 2. Repair and validation summary

### M3

- The 3-body baseline passed the threshold at about 5,900 km.
- Higher-fidelity propagation reduced residuals further, showing that the dominant error source is missing planetary perturbation rather than numerical instability.
- The claim that Jupiter is the main contributor was supported by the repair audits and benchmark comparisons.

### M5

- The old patched-conic saving-ratio story was invalidated.
- The direct no-lunar baselines showed that a fair fixed-date comparison is not available under the tested constraints.
- The project therefore treats the saving ratio as not reported rather than forced.

### M6

- The earlier geometric proxy was replaced by actual trajectory solving.
- The low-return constraint audit showed the search is dominated by the physical return-speed behavior rather than a simple proxy score.
- Some M6 variants remain caveated because the objective mixes geometry and return-event semantics.

### M7

- Sensitivity and step-size convergence were both exercised.
- The main conclusion is that the trajectory response is non-smooth enough that a clean asymptotic convergence order is not meaningful.

## 3. External benchmark and claim verification

The comparison notes established two important points:

1. A number of saved values were being compared across incompatible physical states.
2. The project needed explicit invalidation notes where a quantity was derived from a perihelion state rather than a true Earth-return state.

The repair-verification notes then split the evidence into three buckets:

- actual results
- estimate-only results
- proxy-model-only results

This is the main reason several old numbers were retired from the final narrative.

## 4. Impact analysis summary

The impact review concluded that the following were invalid as final quantitative claims:

- the old M5 lunar saving ratio
- the old M5/M6 return-vinf interpretations when they were evaluated at perihelion rather than at Earth return

What remained valid:

- the actual no-lunar Lambert baseline
- the M3 model-hierarchy diagnostic
- the M4 swingby scan
- the M7 sensitivity and convergence work
- the O3/O3+ and O4/O4+ diagnostic work, with the stated caveats

## 5. Delta-v budget audit

The Δv audit established that the project uses several different budget conventions, and they should not be mixed:

- `M1` patched-conic budget is comparable to the Qian symmetric baseline.
- `M5` and `M6` use different bookkeeping and are not directly comparable to the textbook total.
- Some diagnostic values only represent proxy or correction terms, not full mission budgets.

The practical consequence is that report text must always state which budget basis is being used.

## 6. Operational conclusion

The technical audit trail supports the final project narrative, but only if the report keeps the caveats intact:

- do not reuse invalidated saving-ratio claims
- do not compare incompatible velocity definitions
- do not present proxy searches as full physical searches
- do not hide the distinction between actual results and estimate-only diagnostics

