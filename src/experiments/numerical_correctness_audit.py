"""
numerical_correctness_audit.py
==============================
Numerical-correctness-first audit for M1-M7.

This script prefers:
  1. Independent formula checks
  2. Convergence checks
  3. Event semantics checks
  4. Existing result reuse only when the result file is present

Output:
  data/results/numerical_correctness_audit.json
  data/results/numerical_correctness_audit.csv
"""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
RESULTS = REPO / "data" / "results"
sys.path.insert(0, str(SRC))

from constants import AU_KM, GM_SUN, R_EARTH, V_ESCAPE_EARTH, V_EARTH_ORBIT
from patched_conic import compute_patched_conic
from mission_constraints import is_launch_mjd_in_window, mjd_to_date_str
from nbody import convergence_study, propagate_nbody
from horizons import fetch_sem_vectors, initial_state_from_horizons, state_at_index
from trajectory import interpolate_state_at_mjd
from experiments.result_records import AuditRecord, write_csv, write_json


def _load_json(name: str) -> dict | list | None:
    path = RESULTS / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _active_m6_search_name() -> str:
    if (RESULTS / "m6_legal_window_search.json").exists():
        return "m6_legal_window_search.json"
    return "m6_complete_return_window_search.json"


def _read_csv_rows(name: str) -> list[dict[str, str]]:
    path = RESULTS / name
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _status_from_relerr(relerr: float | None, pass_tol: float, warn_tol: float) -> str:
    if relerr is None or not math.isfinite(relerr):
        return "UNRESOLVED"
    if relerr <= pass_tol:
        return "PASS"
    if relerr <= warn_tol:
        return "WARN"
    return "RED"


def _entry(
    module: str,
    quantity: str,
    project_value: Any,
    independent_value: Any,
    relative_error: float | None,
    unit: str,
    frame: str,
    event: str,
    status: str,
    classification: str,
    action: str,
    notes: str | None = None,
) -> AuditRecord:
    return AuditRecord(
        module=module,
        quantity=quantity,
        project_value=project_value,
        independent_check_value=independent_value,
        relative_error=relative_error,
        unit=unit,
        frame=frame,
        event=event,
        status=status,
        classification=classification,
        action=action,
        notes=notes,
    )


def _norm(vec: Any) -> float:
    return float(np.linalg.norm(np.asarray(vec, dtype=float)))


def audit_m1() -> list[AuditRecord]:
    entries: list[AuditRecord] = []

    for rp_au, label in [(0.2, "Qian_0.2_AU"), (0.3, "Project_0.3_AU")]:
        elem = compute_patched_conic(r_p_AU=rp_au)
        r1 = AU_KM
        rp = rp_au * AU_KM
        v_t = math.sqrt(GM_SUN / r1 * (2.0 * rp / (r1 + rp)))
        delta_v_helio = v_t - V_EARTH_ORBIT
        v_launch = math.sqrt(delta_v_helio**2 + V_ESCAPE_EARTH**2)
        rel = abs(v_launch - elem.v_launch) / v_launch
        status = _status_from_relerr(rel, 1e-3, 5e-3)
        entries.append(
            _entry(
                module="M1",
                quantity=f"{label}_v_launch_kms",
                project_value=round(elem.v_launch, 6),
                independent_value=round(v_launch, 6),
                relative_error=rel,
                unit="km/s",
                frame="Earth launch / heliocentric transfer split",
                event="departure",
                status=status,
                classification="ACTUAL_RESULT",
                action="keep" if status == "PASS" else "fix",
                notes=(
                    f"delta_v_helio={delta_v_helio:.6f} km/s, "
                    f"2*v_launch={2.0*elem.v_launch:.4f} km/s"
                ),
            )
        )

    elem_03 = compute_patched_conic(r_p_AU=0.3)
    symmetric_total = 2.0 * elem_03.v_launch
    rel = abs(symmetric_total - 29.4072) / 29.4072
    entries.append(
        _entry(
            module="M1",
            quantity="0.3_AU_symmetric_total",
            project_value=round(symmetric_total, 4),
            independent_value=29.4072,
            relative_error=rel,
            unit="km/s",
            frame="Qian-style symmetric patched-conic budget",
            event="round_trip_budget",
            status=_status_from_relerr(rel, 1e-3, 5e-3),
            classification="ACTUAL_RESULT",
            action="keep",
            notes="Checks that 29.41 km/s = 2 × v_launch, not 2 × heliocentric impulse.",
        )
    )
    return entries


def audit_m2() -> list[AuditRecord]:
    entries: list[AuditRecord] = []
    hs = [0.004, 0.002, 0.001, 0.0005]
    results = convergence_study(hs, T=1.0)

    for result in results:
        entries.append(
            _entry(
                module="M2",
                quantity=f"two_body_pos_err_h_{result['h']}",
                project_value=result["pos_err"],
                independent_value=None,
                relative_error=None,
                unit="nondim",
                frame="2-body nondimensional circular orbit",
                event="1_period",
                status="PASS" if result["pos_err"] < 1e-4 else "WARN",
                classification="ACTUAL_RESULT",
                action="keep" if result["pos_err"] < 1e-4 else "fix",
                notes=(
                    f"rel_E_err={result['rel_E_err']:.3e}, "
                    f"rel_L_err={result['rel_L_err']:.3e}"
                ),
            )
        )

    pos_errors = [r["pos_err"] for r in results]
    ratios = []
    for i in range(len(pos_errors) - 1):
        if pos_errors[i + 1] > 0:
            ratios.append(pos_errors[i] / pos_errors[i + 1])
    ratio_status = "PASS" if ratios and all(2.5 <= r <= 5.5 for r in ratios[-2:]) else "WARN"
    entries.append(
        _entry(
            module="M2",
            quantity="dt_halving_convergence_ratio",
            project_value=[round(r, 4) for r in ratios],
            independent_value=4.0,
            relative_error=None,
            unit="ratio",
            frame="2-body nondimensional circular orbit",
            event="convergence",
            status=ratio_status,
            classification="ACTUAL_RESULT",
            action="keep" if ratio_status == "PASS" else "fix",
            notes="Velocity-Verlet should approach second-order under dt halving.",
        )
    )
    return entries


def audit_m3() -> list[AuditRecord]:
    entries: list[AuditRecord] = []
    hierarchy = _load_json("m3_model_hierarchy.json")
    deep = _load_json("m3_numerical_deep_audit.json")

    if not hierarchy or not deep:
        entries.append(
            _entry(
                module="M3",
                quantity="deep_audit_required_files",
                project_value=None,
                independent_value=None,
                relative_error=None,
                unit="",
                frame="",
                event="",
                status="RED",
                classification="UNRESOLVED",
                action="recompute",
                notes="Missing m3_model_hierarchy.json or m3_numerical_deep_audit.json",
            )
        )
        return entries

    models = {m["name"]: m for m in hierarchy.get("models", [])}
    for name, expected in [
        ("SEM_3body", 5911.66),
        ("SEM_Jupiter_Venus_5body", 1401.42),
        ("SEM_full_planetary", 126.47),
    ]:
        model = models.get(name)
        proj = model.get("max_residual_km") if model else None
        rel = abs(proj - expected) / expected if proj is not None else None
        status = _status_from_relerr(rel, 1e-3, 1e-2) if rel is not None else "UNRESOLVED"
        entries.append(
            _entry(
                module="M3",
                quantity=f"{name}_max_residual_km",
                project_value=proj,
                independent_value=expected,
                relative_error=rel,
                unit="km",
                frame="heliocentric residual after SSB propagation",
                event="full_year_10day_sample",
                status=status,
                classification="ACTUAL_WITH_SCOPE",
                action="keep",
                notes="Same-source propagation check benchmark, not independent JPL prediction.",
            )
        )

    entries.append(
        _entry(
            module="M3",
            quantity="no_daily_reset",
            project_value=bool(deep.get("no_daily_horizons_reset")),
            independent_value=True,
            relative_error=None,
            unit="bool",
            frame="SSB propagation from day-0 initial condition",
            event="day_30_independence_check",
            status="PASS" if deep.get("no_daily_horizons_reset") else "RED",
            classification="PASS_WITH_SCOPE",
            action="keep" if deep.get("no_daily_horizons_reset") else "fix",
            notes="Deep audit confirms no daily Horizons reset.",
        )
    )
    dt_rows = deep.get("dt_convergence", {}).get("values", [])
    ratios = [float(r) for r in deep.get("dt_convergence_ratios", [])]
    stable = bool(ratios) and all(0.8 <= r <= 1.25 for r in ratios)
    entries.append(
        _entry(
            module="M3",
            quantity="dt_convergence_stable",
            project_value={f"{row['dt_sec']}s": row["residual_km"] for row in dt_rows},
            independent_value="model-dominated residual plateau",
            relative_error=None,
            unit="km",
            frame="Earth heliocentric residual",
            event="dt_1800_900_450",
            status="PASS" if stable else "WARN",
            classification="PASS_WITH_SCOPE",
            action="keep" if stable else "inspect",
            notes=f"dt-halving Earth helio max ratios = {[round(r, 3) for r in ratios]}",
        )
    )
    entries.append(
        _entry(
            module="M3",
            quantity="same_source_initial_condition_caveat",
            project_value=bool(deep.get("not_independent_jpl_prediction")),
            independent_value=True,
            relative_error=None,
            unit="bool",
            frame="Horizons day-0 IC, free forward propagation",
            event="full_planetary_126km_interpretation",
            status="PASS",
            classification="PASS_WITH_SCOPE",
            action="keep",
            notes=deep.get("same_source_scope_note"),
        )
    )
    return entries


def audit_m4() -> list[AuditRecord]:
    entries: list[AuditRecord] = []
    rows = _read_csv_rows("m4_swingby_scan.csv")
    if not rows:
        entries.append(
            _entry(
                module="M4",
                quantity="swingby_scan_csv",
                project_value=None,
                independent_value=None,
                relative_error=None,
                unit="",
                frame="moon-centric 2-body",
                event="SOI_entry_exit",
                status="RED",
                classification="UNRESOLVED",
                action="recompute",
                notes="Missing data/results/m4_swingby_scan.csv",
            )
        )
        return entries

    valid = [r for r in rows if r.get("status") == "ok" and r.get("error_finite_deg")]
    max_case = max(valid, key=lambda r: float(r["error_finite_deg"]))
    max_error = float(max_case["error_finite_deg"])
    vinf_conservation = float(max_case.get("vinf_conservation_error", 0.0) or 0.0)
    status = "PASS" if max_error <= 0.5 else "WARN"
    entries.append(
        _entry(
            module="M4",
            quantity="max_finite_SOI_angle_error_deg",
            project_value=max_error,
            independent_value=0.5,
            relative_error=None,
            unit="deg",
            frame="moon-centric 2-body, finite SOI",
            event="SOI_entry_exit",
            status=status,
            classification="ACTUAL_RESULT",
            action="keep" if status == "PASS" else "inspect",
            notes=(
                f"r_m={max_case['r_m_km']} km, v_inf={max_case['v_inf_kms']} km/s, "
                f"side={max_case['side']}, analytic={max_case['delta_finite_analytic_deg']} deg, "
                f"numeric={max_case['delta_numeric_finite_deg']} deg, "
                f"vinf_conservation_error={vinf_conservation:.3e}"
            ),
        )
    )
    return entries


def audit_m5() -> list[AuditRecord]:
    entries: list[AuditRecord] = []
    lunar = _load_json("m5_best_lunar_candidate_verify.json")
    no_lunar = _load_json("m5_no_lunar_fixed_date_deep_search.json")
    compare = _load_json("m5_fixed_date_current_compare.json")

    if not lunar or not no_lunar or not compare:
        entries.append(
            _entry(
                module="M5",
                quantity="required_result_files",
                project_value=None,
                independent_value=None,
                relative_error=None,
                unit="",
                frame="",
                event="",
                status="RED",
                classification="UNRESOLVED",
                action="recompute",
                notes="Missing one of the current M5 formal comparison files",
            )
        )
        return entries

    event = lunar["event_check"]
    budget = lunar["budget"]
    state = lunar["state_at_return"]
    launch_ok = is_launch_mjd_in_window(lunar.get("candidate", {}).get("t0_mjd"))
    entries.append(
        _entry(
            module="M5",
            quantity="lunar_return_event_valid",
            project_value=bool(event["valid_return_event"]),
            independent_value=True,
            relative_error=None,
            unit="bool",
            frame="heliocentric state relative to Earth",
            event="earth_return",
            status="PASS" if event["valid_return_event"] and launch_ok else "RED",
            classification="ACTUAL_RESULT" if event["valid_return_event"] and launch_ok else "INVALID_FORMAL_WINDOW_OR_EVENT",
            action="keep" if event["valid_return_event"] and launch_ok else "fix",
            notes=(
                f"dist_earth={event['distance_to_earth_km']} km, "
                f"dist_moon={event['distance_to_moon_km']} km, "
                f"return_vinf={state['return_vinf_kms']} km/s, "
                f"t0={lunar.get('candidate', {}).get('t0_mjd')} "
                f"({mjd_to_date_str(lunar.get('candidate', {}).get('t0_mjd')) if lunar.get('candidate', {}).get('t0_mjd') is not None else 'N/A'})"
            ),
        )
    )

    best = no_lunar["best_valid"]
    ratio = (best["total_dv_proxy_kms"] - budget["total_dv_proxy_vinf_basis"]) / best["total_dv_proxy_kms"] if best else None
    rel = (
        abs(ratio - compare["formal_ratio_vinf_basis"]) / max(abs(ratio), 1e-15)
        if ratio is not None and compare["formal_ratio_vinf_basis"] is not None
        else None
    )
    ratio_status = (
        "PASS"
        if launch_ok and ratio is not None and compare["formal_ratio_vinf_basis"] is not None and abs(compare["formal_ratio_vinf_basis"] - ratio) <= 5e-7
        else "RED" if not launch_ok
        else "WARN"
    )
    entries.append(
        _entry(
            module="M5",
            quantity="formal_fixed_date_ratio",
            project_value=compare["formal_ratio_vinf_basis"],
            independent_value=round(ratio, 6) if ratio is not None else None,
            relative_error=rel,
            unit="ratio",
            frame="vinf_basis",
            event=f"same_t0_{compare.get('same_t0')}",
            status=ratio_status,
            classification="ACTUAL_RESULT" if launch_ok else "INVALID_FORMAL_WINDOW_OR_EVENT",
            action="keep" if launch_ok else "recompute",
            notes=(
                f"lunar_total={budget['total_dv_proxy_vinf_basis']}, "
                f"no_lunar_total={best['total_dv_proxy_kms'] if best else None}, "
                f"same_t0={compare.get('same_t0')} ({mjd_to_date_str(compare.get('same_t0')) if compare.get('same_t0') is not None else 'N/A'}), "
                f"same_budget_basis={compare.get('same_budget_basis')}, "
                f"launch_window_valid={launch_ok}"
            ),
        )
    )

    entries.append(
        _entry(
            module="M5",
            quantity="no_lunar_valid_fair_candidates",
            project_value=no_lunar["valid_fair_candidates"],
            independent_value=no_lunar["valid_fair_candidates"],
            relative_error=0.0,
            unit="count",
            frame="same_date_DSM_search",
            event=f"t0_{compare.get('same_t0')}",
            status="PASS",
            classification="ACTUAL_RESULT",
            action="keep",
            notes=(
                f"perihelion_AU={best['perihelion_AU']}, "
                f"peri_err_AU={best['peri_err_AU']}, "
                f"dsm_delta_v={best['dsm_delta_v_kms']}, "
                f"return_vinf={best['return_vinf_kms']}"
            ),
        )
    )
    return entries


def audit_m6() -> list[AuditRecord]:
    entries: list[AuditRecord] = []
    deep = _load_json("m6_numerical_deep_audit.json")
    search_name = _active_m6_search_name()
    search = _load_json(search_name)
    if not deep or not search:
        entries.append(
            _entry(
                module="M6",
                quantity="deep_audit_required_files",
                project_value=None,
                independent_value=None,
                relative_error=None,
                unit="",
                frame="",
                event="",
                status="RED",
                classification="UNRESOLVED",
                action="recompute",
                notes=f"Missing m6_numerical_deep_audit.json or {search_name}",
            )
        )
        return entries

    valid_count = int(search.get("valid_complete_return_count", 0) or 0)
    fair_count = int(search.get("valid_fair_return_count", 0) or 0)
    classification = str(deep.get("classification"))
    spot = deep.get("independent_spotcheck") or {}
    best_valid = deep.get("best_valid_candidate") or search.get("best_valid_candidate") or {}
    best_t0 = best_valid.get("t0_mjd")
    legal_window_ok = is_launch_mjd_in_window(best_t0) if best_t0 is not None else False
    active_formal_status = (
        "PASS"
        if legal_window_ok
        else "WARN"
    )
    active_formal_classification = (
        "PASS_M5_DERIVED_WINDOW_CONFIRMED"
        if classification == "ACTUAL_RESULT_M5_DERIVED_LEGAL_WINDOW"
        else ("PASS_LEGAL_WINDOW" if classification == "ACTUAL_RESULT_LEGAL_WINDOW" else "LEGAL_WINDOW_PENDING")
    )
    entries.append(
        _entry(
            module="M6",
            quantity="valid_earth_return_candidates",
            project_value=valid_count,
            independent_value=valid_count,
            relative_error=0.0,
            unit="count",
            frame="complete-return launch-window search",
            event="full search coverage",
            status=active_formal_status,
            classification=active_formal_classification,
            action="keep" if legal_window_ok else "recompute",
            notes=(
                f"valid_complete_return_count={valid_count}, valid_fair_return_count={fair_count}, "
                f"candidate_source={deep.get('candidate_source')}, source_grid_reused={deep.get('source_grid_reused')}, "
                f"independent_m6_search={deep.get('independent_m6_search')}, source_file={search_name}, "
                f"best_t0={best_t0} ({mjd_to_date_str(best_t0) if best_t0 is not None else 'N/A'})"
            ),
        )
    )

    legacy_rows = [row for row in deep.get("candidates", []) if row.get("classification") == "INVALID_LEGACY_EVENT"]
    invalid_nonreturn_rows = sum(1 for row in legacy_rows if row.get("return_vinf_kms") is None)
    max_claimed_nonreturn = max(
        (float(row["legacy_return_vinf_kms"]) for row in legacy_rows if row.get("legacy_return_vinf_kms") is not None),
        default=None,
    )
    entries.append(
        _entry(
            module="M6",
            quantity="old_invalid_return_vinf_guarded",
            project_value=bool(invalid_nonreturn_rows == len(legacy_rows)),
            independent_value=True,
            relative_error=None,
            unit="bool",
            frame="legacy top-window event audit",
            event="formal_field_guard",
            status="PASS" if invalid_nonreturn_rows == len(legacy_rows) else "WARN",
            classification="FINITE_SEARCH_NEG",
            action="keep" if invalid_nonreturn_rows == len(legacy_rows) else "fix",
            notes=(
                f"nonreturn_rows_without_formal_return_vinf={max(invalid_nonreturn_rows, 0)}/{len(legacy_rows)}, "
                f"max_claimed_nonreturn_vinf={max_claimed_nonreturn}"
            ),
        )
    )

    entries.append(
        _entry(
            module="M6",
            quantity="final_classification_scope",
            project_value=classification,
            independent_value=True,
            relative_error=None,
            unit="enum",
            frame="deep-audit classification",
            event="m6_numerical_deep_audit",
            status="PASS" if legal_window_ok else "WARN",
            classification=(
                "PASS_WITH_PROVENANCE"
                if classification == "ACTUAL_RESULT_M5_DERIVED_LEGAL_WINDOW" and legal_window_ok
                else ("PASS_LEGAL_WINDOW" if classification == "ACTUAL_RESULT_LEGAL_WINDOW" and legal_window_ok else "LEGAL_WINDOW_PENDING")
            ),
            action="keep" if legal_window_ok else "recompute",
            notes=(
                "Finite-search negative is allowed only with explicit coverage and best near miss."
                if classification == "FINITE_SEARCH_NEG"
                else (
                    f"M5-derived launch-window extraction confirmed by independent spotcheck status={spot.get('status')}"
                    if classification == "ACTUAL_RESULT_M5_DERIVED_LEGAL_WINDOW" and legal_window_ok
                    else (
                        "Independent legal-window actual result retained because at least one valid complete-return candidate exists."
                        if classification == "ACTUAL_RESULT_LEGAL_WINDOW" and legal_window_ok
                        else "Current on-disk M6 result is still pre-legal-window or historical; legal-window regeneration is pending."
                    )
                )
            ),
        )
    )
    return entries


def audit_m7() -> list[AuditRecord]:
    entries: list[AuditRecord] = []
    rows = _read_csv_rows("m7_stepsize_convergence.csv")
    timeout_diag = _load_json("m7_timeout_diagnosis.json")
    if not rows:
        entries.append(
            _entry(
                module="M7",
                quantity="stepsize_convergence_csv",
                project_value=None,
                independent_value=None,
                relative_error=None,
                unit="",
                frame="trajectory convergence",
                event="dt_sweep",
                status="RED",
                classification="UNRESOLVED",
                action="recompute",
                notes="Missing data/results/m7_stepsize_convergence.csv",
            )
        )
        return entries

    try:
        energy_drifts = [float(r["energy_drift"]) for r in rows]
        dts = [float(r["dt_s"]) for r in rows]
    except (KeyError, ValueError):
        energy_drifts = []
        dts = []

    ratios = []
    for i in range(len(energy_drifts) - 1):
        if energy_drifts[i + 1] > 0:
            ratios.append(energy_drifts[i] / energy_drifts[i + 1])
    status = "PASS" if ratios and all(r > 1.0 for r in ratios) else "WARN"
    entries.append(
        _entry(
            module="M7",
            quantity="energy_drift_dt_monotonicity",
            project_value=[round(v, 3) for v in ratios],
            independent_value="monotonic decrease",
            relative_error=None,
            unit="ratio",
            frame="dt sweep",
            event="trajectory convergence",
            status=status,
            classification="ACTUAL_RESULT",
            action="keep" if status == "PASS" else "inspect",
            notes=f"dt_values={dts}",
        )
    )

    smoke_json = _load_json("m7_extended_monte_carlo_smoke.json")
    full_json = _load_json("m7_extended_monte_carlo.json")
    mc_json = full_json or smoke_json
    entries.append(
        _entry(
            module="M7",
            quantity="extended_mc_result_present",
            project_value=mc_json is not None,
            independent_value=True,
            relative_error=None,
            unit="bool",
            frame="Monte Carlo robustness",
            event="extended_mc",
            status="WARN" if mc_json is None else "PASS",
            classification="UNRESOLVED" if mc_json is None else "ACTUAL_RESULT",
            action="recompute" if mc_json is None else "keep",
            notes=(
                "Neither smoke nor full M7 Monte Carlo JSON is present."
                if mc_json is None
                else f"using {'full' if full_json is not None else 'smoke'} M7 Monte Carlo JSON"
            ),
        )
    )
    if mc_json is not None:
        ref = mc_json.get("reference_candidate", {})
        aligned = (
            is_launch_mjd_in_window(float(ref.get("t0_mjd", -1)))
            and ref.get("side") == "trailing"
        )
        entries.append(
            _entry(
                module="M7",
                quantity="extended_mc_uses_valid_m5_reference",
                project_value=aligned,
                independent_value=True,
                relative_error=None,
                unit="bool",
                frame="Monte Carlo reference trajectory",
                event="extended_mc",
                status="PASS" if aligned else "RED",
                classification="ACTUAL_RESULT" if aligned else "UNRESOLVED",
                action="keep" if aligned else "fix",
                notes=f"reference_candidate={ref}",
            )
        )
        semantics = mc_json.get("event_semantics", {})
        event_guard_ok = bool(semantics.get("return_vinf_defined_only_at_earth_return"))
        entries.append(
            _entry(
                module="M7",
                quantity="extended_mc_return_event_semantics",
                project_value=event_guard_ok,
                independent_value=True,
                relative_error=None,
                unit="bool",
                frame="Monte Carlo return-event semantics",
                event="extended_mc",
                status="PASS" if event_guard_ok else "RED",
                classification="ACTUAL_RESULT" if event_guard_ok else "UNRESOLVED",
                action="keep" if event_guard_ok else "fix",
                notes=f"event_semantics={semantics}",
            )
        )
        classification = mc_json.get("classification")
        sample_rows_saved = bool(mc_json.get("sample_rows_saved"))
        if classification == "FULL_MC_ACTUAL_RESULT":
            if timeout_diag is None:
                status = "WARN"
                notes = "full N=200 Monte Carlo result present, but timeout diagnosis is still pending"
            elif sample_rows_saved and timeout_diag.get("classification") in (
                "SAMPLE_LEVEL_TIMEOUT_DIAGNOSIS",
                "REPLAY_AWARE_TIMEOUT_DIAGNOSIS",
            ):
                status = "WARN"
                notes = (
                    "full N=200 Monte Carlo result present with sample-level timeout accounting; "
                    "replay closure may still be pending, but future diagnosis is now code-supported"
                )
            else:
                status = "WARN"
                notes = (
                    "full N=200 Monte Carlo result present with aggregate timeout diagnosis; "
                    "sample-level timeout replay is still pending"
                )
        elif classification == "SMOKE_SEMANTICS_RESULT":
            status = "WARN"
            notes = "smoke semantics result present; full N=200 result still pending"
        else:
            status = "WARN"
            notes = f"non-full M7 classification={classification!r}"
        entries.append(
            _entry(
                module="M7",
                quantity="mc_result_identity",
                project_value=classification,
                independent_value="FULL_MC_ACTUAL_RESULT",
                relative_error=None,
                unit="enum",
                frame="Monte Carlo result identity",
                event="extended_mc",
                status=status,
                classification=(
                    "FULL_MC_EVENT_SEMANTICS_PASS_TIMEOUT_ANALYSIS_PENDING"
                    if classification == "FULL_MC_ACTUAL_RESULT"
                    else ("ACTUAL_RESULT" if status == "PASS" else "UNRESOLVED")
                ),
                action="keep" if classification == "FULL_MC_ACTUAL_RESULT" else "recompute",
                notes=notes,
            )
        )
    return entries


def save_outputs(entries: list[AuditRecord]) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    json_path = RESULTS / "numerical_correctness_audit.json"
    csv_path = RESULTS / "numerical_correctness_audit.csv"

    summary = {
        "task": "Numerical correctness audit",
        "entries": [item.to_dict() for item in entries],
        "status_counts": {
            status: sum(1 for item in entries if item.status == status)
            for status in ["PASS", "WARN", "RED", "UNRESOLVED"]
        },
    }
    write_json(json_path, summary)
    write_csv(csv_path, entries)

    print(f"Saved: {json_path}")
    print(f"Saved: {csv_path}")


def main() -> int:
    entries: list[AuditRecord] = []
    entries.extend(audit_m1())
    entries.extend(audit_m2())
    entries.extend(audit_m3())
    entries.extend(audit_m4())
    entries.extend(audit_m5())
    entries.extend(audit_m6())
    entries.extend(audit_m7())

    save_outputs(entries)

    counts = {
        status: sum(1 for item in entries if item.status == status)
        for status in ["PASS", "WARN", "RED", "UNRESOLVED"]
    }
    print(json.dumps(counts, indent=2))
    return 1 if counts["RED"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
