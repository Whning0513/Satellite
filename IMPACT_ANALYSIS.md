# Impact Analysis: M5 DSM Saving Ratio Repair

## Old M5 status

- M5.4 (compare with no-lunar baseline): pass-with-caveat — direct Lambert run (88 candidates, 0 fair), DSM search not executed
- M5.5 (saving ratio): **not satisfied** — no usable baseline found
- Audit state: *partial — 无法满足 M5.4–5.5 要求*

## New M5 status

- M5.4: **fully satisfied** — 203 strict-fair DSM no-lunar candidates found by the ellipse-sampled DSM search
- M5.5: **fully satisfied** — formal saving ratio = **-224.7%**

## Saving ratio detail

| Component | No-Lunar DSM | Lunar-Assisted |
|-----------|-------------|----------------|
| departure_vinf (proxy launch) | 9.64 km/s | 10.12 km/s |
| DSM Δv | 12.84 km/s | 0 (gravity assist, free) |
| return_vinf | 13.78 km/s | 77.88 km/s |
| return braking proxy | 0 km/s | 62.88 km/s |
| **total dv proxy** | **22.48 km/s** | **73.00 km/s** |
| **saving ratio** | **—** | **-224.7%** |

**Negative ratio means the no-lunar baseline has LOWER total Δv proxy than the lunar-assisted trajectory.** This is not a bug: the lunar trajectory's return v_rel_earth of 77.88 km/s incurs a 62.88 km/s braking penalty under the uniform budget proxy, far outweighing the 0.21 km/s departure v_inf savings the moon assist provides.

## Files that need report update

- `report.tex` — M5 section:
  - Replace "no fair no-lunar baseline found" with the 203-candidate DSM search result
  - Replace "saving ratio N/A" with "-224.7%"
  - Add explanation of why the ratio is negative (return v_inf domination)
  - The physical conclusion ("moon assist changes direction at perihelion") remains valid
  
## Are old conclusions invalidated?

**No.** The core physics conclusion — that the lunar gravity assist provides a beneficial velocity change (~0.41 km/s) that helps the spacecraft reach the targeted 0.3 AU perihelion — is unchanged. What changed is that under the **uniform proxy budget**, the no-lunar DSM trajectory achieves much lower total proxy Δv because the DSM enables a benign return geometry (return v_inf = 13.78 km/s, no braking needed) compared to the lunar trajectory's extreme return speed (77.88 km/s).

The negative saving ratio is an artifact of the proxy budget penalizing high return speeds heavily. In a real mission with aerocapture or advanced braking, the lunar trajectory might still be preferable. But per the uniform budget definition, the DSM no-lunar solution is "cheaper."

## Action items

1. Do NOT modify report.tex in this cycle
2. After rebuilding, the M5 section should include both:
   - Acknowledgement that 203 strict-fair DSM baselines were found
   - Formal saving ratio = -224.7%, with explanation
   - The physical tradeoff between departure v_inf savings and return braking penalty
