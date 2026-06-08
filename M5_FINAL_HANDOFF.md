# M5 Final Handoff

## Status: done-with-caveat

### Three baselines
1. **Patched-conic reference**: deprecated for saving comparison (inconsistent basis).
2. **SOI-exit tangent propagation**: demonstrates that rp≈0.3 AU is reachable without lunar assist, but Earth return is not achieved at the tested fixed launch dates.
3. **Earth-to-Earth Lambert search**: systematic fixed-date direct return search (100–730d tof, 4 branches, 0.25d fine step).

### Lambert search results
| t0 | candidates | feasible | near_feasible | best_rp | tof | return v_inf | status |
|----|-----------:|--------:|-------------:|-------:|---:|-------------:|--------|
| 61066 | 358 | 0 | 14 | 0.3011 AU | 271.5d | 26.24 km/s | partial_tradeoff |
| 61154 | 380 | 0 | 0 | 0.4721 AU | 287.5d | 64.06 km/s | invalid_no_matching_perihelion |

### Why saving ratio is not reported
No no-lunar candidate satisfies both rp match (error <10%) AND reentry v_inf ≤ 15 km/s at the tested fixed launch dates.

### Result files
- `data/results/m5_fair_no_lunar_baseline.json`
- `data/results/m5_fair_no_lunar_baseline.csv`
- `data/results/m5_no_lunar_lambert_baseline.json`
- `data/results/m5_no_lunar_lambert_baseline.csv`
- `data/results/m5_no_lunar_lambert_pareto.json`
- `data/results/m5_no_lunar_lambert_pareto.png`

### Verification
```bash
make validate-m5
make audit
```

### Do not modify M5 further unless extending global no-lunar search
The current fixed-date Lambert search is sufficient for comparison against the two lunar-optimized windows. Do not iterate further on M5 without a project-wide no-lunar search expansion.
