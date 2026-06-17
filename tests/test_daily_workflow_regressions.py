import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from experiments import export_main_task_result as export_main
from experiments import refresh_legal_window_summary_fields as refresh


def _sample_lunar_row(*, t0_mjd: float, fair: bool, valid: bool, dv_total_kms: float) -> dict:
    return {
        "t0_mjd": t0_mjd,
        "t0_date": "2026-12-14",
        "side": "leading",
        "r_m_km": 9737.4,
        "departure_vinf_kms": 10.1213,
        "launch_equivalent_kms": 15.0854,
        "perihelion_AU": 0.278785,
        "perihelion_error_AU": 0.021215,
        "swingby_dv_kms": 0.094088,
        "dist_moon_min_km": 1263.7,
        "valid_return_event": valid,
        "distance_to_earth_km": 953715.8,
        "distance_to_moon_km": 1270853.2,
        "return_event_mjd": 61741.99,
        "return_vinf_kms": 10.6477,
        "return_braking_kms": 0.0,
        "dv_launch_kms": 15.0854,
        "dv_lunar_residual_kms": 0.0941,
        "dv_reentry_kms": 0.0,
        "dv_total_kms": dv_total_kms,
        "budget_basis": "three_segment_formal",
        "total_vinf_basis_kms": 10.1213,
        "fair": fair,
        "used_nominal_window": True,
        "fallback_full_window_used": False,
        "classification": "ACTUAL_RESULT" if fair and valid else "FINITE_SEARCH_NEG",
    }


class RefreshLegalWindowSummaryFieldsTests(unittest.TestCase):
    def test_refresh_m6_daily_uses_verified_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            results = Path(tmpdir)
            payload = {
                "classification": "ACTUAL_RESULT_DAILY_VERIFIED_LEGAL_WINDOW",
                "verified_candidates": [
                    _sample_lunar_row(t0_mjd=61360.5, fair=True, valid=True, dv_total_kms=15.1794),
                    _sample_lunar_row(t0_mjd=61388.5, fair=False, valid=False, dv_total_kms=15.1795),
                ],
            }
            path = results / "m6_legal_window_daily_verify.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            with mock.patch.object(refresh, "RESULTS", results):
                refresh._refresh_m6_file("m6_legal_window_daily_verify.json")

            refreshed = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(refreshed["total_candidates_evaluated"], 2)
            self.assertEqual(refreshed["valid_complete_return_count"], 1)
            self.assertEqual(refreshed["valid_fair_return_count"], 1)
            self.assertIsNotNone(refreshed["best_verified_candidate"])
            self.assertEqual(refreshed["best_verified_candidate"]["t0_mjd"], 61360.5)
            self.assertEqual(len(refreshed["verified_candidates"]), 2)


class ExportMainTaskResultTests(unittest.TestCase):
    def test_main_reuses_existing_fixed_anchor_when_old_m5_files_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            results = Path(tmpdir)
            existing_export = {
                "fixed_date_formal_anchor": {
                    "candidate_label": "fixed_date_formal_anchor",
                    "t0_mjd": 61065.0,
                    "t0_date": "2026-01-25",
                    "valid_return_event": True,
                    "duration_constraint_valid": True,
                    "distance_to_earth_km": 1000.0,
                    "return_event_mjd": 61431.12,
                    "return_vinf_kms": 10.0,
                    "perihelion_achieved_AU": 0.3,
                    "three_segment_budget": {
                        "budget_basis": "three_segment_formal",
                        "dv_launch_kms": 1.0,
                        "dv_lunar_residual_kms": 2.0,
                        "dv_reentry_kms": 0.0,
                        "dv_total_kms": 3.0,
                    },
                    "three_segment_budget_proxy": {
                        "budget_basis": "three_segment_formal",
                        "dv_launch_kms": 1.0,
                        "dv_lunar_residual_kms": 2.0,
                        "dv_reentry_kms": 0.0,
                        "dv_total_kms": 3.0,
                    },
                    "vinf_basis_budget": {
                        "departure_vinf_kms": 10.0,
                        "total_vinf_basis_kms": 10.0,
                    },
                    "same_date_no_lunar_compare": {
                        "same_budget_basis": True,
                        "budget_basis": "three_segment_formal",
                        "formal_ratio": 0.1,
                    },
                }
                ,
                "invalidated_formal_results_guard": {
                    "resolver_status": "formal_fixed_date_positive_ratio",
                    "current_formal_fixed_date_ratio": 0.391088,
                },
            }
            (results / "main_task_result.json").write_text(json.dumps(existing_export), encoding="utf-8")
            with (results / "main_task_trajectory.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["candidate_label", "mjd"])
                writer.writeheader()
                writer.writerow({"candidate_label": "fixed_date_formal_anchor", "mjd": "61065.0"})

            load_map = {
                "m5_best_lunar_candidate_verify.json": {"candidate": {"t0_mjd": 61065.0}},
                "m5_legal_window_search.json": {
                    "classification": "LEGAL_WINDOW_DAILY_SCAN",
                    "search_rows": [_sample_lunar_row(t0_mjd=61388.5, fair=True, valid=True, dv_total_kms=15.1795)],
                },
                "m7_extended_monte_carlo.json": {
                    "classification": "M7",
                    "reference_candidate": {"t0_mjd": 61388.5},
                    "valid_return_count": 1,
                    "valid_return_rate": 0.5,
                },
            }

            def fake_load_json(name: str) -> dict:
                if name in (
                    "m5_fixed_date_current_compare.json",
                    "m5_no_lunar_fixed_date_deep_search.json",
                    "m5_saving_ratio_resolved.json",
                ):
                    raise FileNotFoundError(name)
                if name == "main_task_result.json":
                    return json.loads((results / name).read_text(encoding="utf-8"))
                return load_map[name]

            legal_block = {
                "candidate_label": "best_legal_window_candidate",
                "t0_mjd": 61388.5,
                "t0_date": "2026-12-14",
                "valid_return_event": True,
                "duration_constraint_valid": True,
                "distance_to_earth_km": 953715.8,
                "return_event_mjd": 61741.99,
                "return_vinf_kms": 10.6477,
                "perihelion_achieved_AU": 0.278785,
                "three_segment_budget": {
                    "budget_basis": "three_segment_formal",
                    "dv_launch_kms": 15.0,
                    "dv_lunar_residual_kms": 0.1,
                    "dv_reentry_kms": 0.0,
                    "dv_total_kms": 15.1,
                },
                "three_segment_budget_proxy": {
                    "budget_basis": "three_segment_formal",
                    "dv_launch_kms": 15.0,
                    "dv_lunar_residual_kms": 0.1,
                    "dv_reentry_kms": 0.0,
                    "dv_total_kms": 15.1,
                },
                "vinf_basis_budget": {
                    "departure_vinf_kms": 10.1213,
                    "total_vinf_basis_kms": 10.1213,
                },
                "provenance": {
                    "independent_m6_search": True,
                },
            }
            legal_rows = [{"candidate_label": "best_legal_window_candidate", "mjd": 61388.5}]

            annual_payload = {
                "classification": "ACTUAL_RESULT_DAILY_VERIFIED_LEGAL_WINDOW",
                "verified_candidates": [_sample_lunar_row(t0_mjd=61388.5, fair=True, valid=True, dv_total_kms=15.1795)],
                "independent_m6_search": True,
            }

            with mock.patch.object(export_main, "RESULTS", results), \
                mock.patch.object(export_main, "_load_json", side_effect=fake_load_json), \
                mock.patch.object(export_main, "fetch_sem_vectors", return_value={}), \
                mock.patch.object(export_main, "load_final_annual_candidate", return_value={"payload": annual_payload, "source_file": "m6_legal_window_daily_verify.json"}), \
                mock.patch.object(export_main, "_best_legal_window_block", return_value=(legal_block, legal_rows)), \
                mock.patch.object(export_main, "_fixed_date_formal_block", side_effect=AssertionError("should reuse existing fixed anchor")):
                rc = export_main.main()

            self.assertEqual(rc, 0)
            written = json.loads((results / "main_task_result.json").read_text(encoding="utf-8"))
            self.assertEqual(written["fixed_date_formal_anchor"]["t0_mjd"], 61065.0)
            self.assertEqual(written["best_legal_window_candidate"]["t0_mjd"], 61388.5)
            self.assertEqual(
                written["invalidated_formal_results_guard"]["resolver_status"],
                "formal_fixed_date_positive_ratio",
            )


if __name__ == "__main__":
    unittest.main()
