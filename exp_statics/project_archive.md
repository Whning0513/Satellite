# Project Archive

This file consolidates the handoff, traceability, and project-dump documents that were previously scattered at the repository root.

## Source documents absorbed

- `M5_FINAL_HANDOFF.md`
- `M5_REAL_REPAIR_AUDIT.md`
- `PROJECT_DETAIL_DUMP.md`
- `PROJECT_FINAL_HANDOFF.md`
- `REQUIREMENT_TRACEABILITY.md`

## 1. Requirement traceability summary

The project maps the implementation to the M1–M8 requirements as follows:

| ID | Status | Notes |
|---|---|---|
| M1 | pass | patched conic regression |
| M2 | pass | N-body integrator regression |
| M3 | pass | Horizons comparison with caveat on fidelity hierarchy |
| M4 | pass | lunar swingby regression with local validation |
| M5 | pass with caveat | no fair no-lunar saving ratio reported |
| M6 | pass | launch-window search and refinement |
| M7 | pass | sensitivity and step-size convergence |
| M8 | pass | figure generation and manifest |

## 2. M5 handoff summary

The M5 handoff was rewritten around a more cautious comparison framework:

- the patched-conic number remains a regression reference only
- the SOI-exit propagation shows the trajectory shape but does not establish Earth return
- the Earth-to-Earth Lambert search is the real no-lunar baseline

The key project-level conclusion is that the fixed-date no-lunar comparison does not produce a fair saving ratio under the tested constraints.

## 3. M5 repair summary

The repair audit makes the final state explicit:

- the lunar-return narrative was invalidated where it depended on a perihelion state treated as Earth return
- the direct Lambert baseline remains valid
- the project should describe M5 as `done-with-caveat`, not as a clean savings win

## 4. Final handoff summary

The final handoff document records the overall submission posture:

- M1–M8 are complete
- the optional work is documented with caveats
- the report and audit files are intended to make the submission self-contained

## 5. Project detail snapshot

The project dump captured the repository state at the time of the review:

- root-level structure and major source modules
- data/result layout
- the role of `AI-Agent.md`, `FINAL_AUDIT.md`, and `README.md`
- the fact that the repo relies on generated results and caches in `data/`

This archive keeps that material in one place so the root stays focused on the user-facing documents.

## 6. Practical reading order

If someone needs the shortest path through the archive:

1. Read `README.md`
2. Read `FINAL_AUDIT.md`
3. Read `AI-Agent.md`
4. Read `exp_statics/project_archive.md`
5. Read `exp_statics/engineering_audit_archive.md`

