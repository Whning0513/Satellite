# Impact Analysis: M5 DSM Saving Ratio Repair (Corrected)

## Old M5 status

- M5.4 (compare with no-lunar baseline): pass-with-caveat — direct Lambert run (88 candidates, 0 fair), DSM search not executed
- M5.5 (saving ratio): **not satisfied** — no usable baseline found
- Audit state: *partial — 无法满足 M5.4–5.5 要求*

## New M5 status

- **M5 fixed-date comparison completed.**
- 203 strict-fair DSM no-lunar candidates found, including **18 at the same launch date** as the lunar candidate (t0 = MJD 61066).
- The formal fixed-date saving ratio is **−187.3%** (negative, meaning no-lunar is cheaper under the proxy).
- **The cross-date −224.7% value previously reported is invalid** because it compared DSM at t0=61125 vs lunar at t0=61066.

## Fixed-date comparison detail

Both trajectories launched at t0 = MJD 61066.

| Component | Lunar | No-Lunar DSM |
|-----------|-------|-------------|
| departure_vinf | 10.12 km/s | 10.01 km/s |
| dsm / lunar residual | 0.00 km/s (gravity assist) | 15.40 km/s (DSM) |
| return_vinf | 77.88 km/s | 5.97 km/s |
| return braking proxy | 62.88 km/s | 0.00 km/s |
| **total_dv_proxy** | **73.00 km/s** | **25.41 km/s** |
| **saving ratio** | — | **-187.3%** |

## Budget sensitivity (3 modes, all negative)

| Mode | Lunar total | No-lunar total | Saving ratio | Lunar saves? |
|------|-----------:|---------------:|------------:|:----------:|
| A: threshold braking | 73.00 | 25.41 | -187.3% | No |
| B: full return braking | 88.00 | 31.38 | -180.5% | No |
| C: entry speed proxy | 73.80 | 25.41 | -190.5% | No |

All three reasonable budget proxies give negative saving ratios. The conclusion that the current lunar candidate does not save Δv under uniform proxy is robust.

## Important caveat

The negative ratio is a result of the **proxy budget definition**: it penalises high return speed heavily (62.88 km/s braking term). In a real mission with aerocapture, advanced thermal protection, or propulsive braking the trade-off would be different. What the proxy shows is that the DSM no-lunar trajectory achieves a much more benign return geometry (return_vinf = 5.97 km/s vs 77.88 km/s) at the cost of a 15.40 km/s deep-space manoeuvre — which under this budget formula is the cheaper option.

## Files that need report update

- `report.tex` — M5 section:
  - Replace "no fair no-lunar baseline found" with the 18-candidate fixed-date DSM search result
  - Replace "saving ratio N/A" with "-187.3%" and explain the negative sign
  - Note that the cross-date global best gives -224.7% but this is not the formal fixed-date ratio
  - The physical conclusion ("moon assist changes velocity direction at swingby") remains valid

## Are old conclusions invalidated?

**The core physics is unchanged.** The lunar gravity assist provides ~0.41 km/s velocity change at the Moon. What changed is the **budget accounting**: under a uniform proxy that counts `departure_vinf + residual + max(0, return_vinf − 15)`, the DSM no-lunar trajectory (return_vinf = 5.97 km/s) is cheaper than the lunar trajectory (return_vinf = 77.88 km/s) because the braking term dominates.

## Action items

1. Do NOT modify report.tex in this cycle
2. Use the corrected fixed-date ratio (−187.3%) when report.tex is updated
3. Ensure cross-date −224.7% is never cited as the formal M5 ratio
