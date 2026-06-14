# MSPJ Final Project — Makefile
#
# Targets:
#   all        — default: compile + m3 + figures + pdf
#   compile    — python -m compileall src (syntax check)
#   validate   — run all regression tests (m1-m8)
#   validate-m3 — run M3 regression only
#   validate-m4 — run M4 regression only
#   validate-m5 — run M5 fair + Lambert baselines
#   pdf        — build report.pdf via xelatex
#   figures    — generate all M8 figures (requires m3 residuals)
#   animation  — generate orbit animation MP4/GIF (not in default all)
#   scan-fast  — fast geometric launch-window scan (M6)
#   m1..m8     — run individual regression test cases
#   m5-fair    — SOI-exit no-lunar tangent baseline
#   m5-lambert — Earth-to-Earth Lambert no-lunar baseline
#   o3         — test shooting corrector
#   o1-3d, o2-gr, o4-mga, o6-interactive, o7-parallel, o7-surrogate — optional extensions
#   o7-benchmark — 3-run repeated benchmark for O7
#   bonus-all  — all optional extensions
#   audit      — security + figure-reference + M5-files + repo-size check
#   clean      — remove cache / build artifacts

PYTHON := python
REPORT_IMAGES := $(wildcard data/results/m8_*.png)

.PHONY: all compile validate validate-m3 validate-m4 validate-m5
.PHONY: m1 m2 m3 m4 m5 m6 m7 m8 o3 o1-3d m5-fair m5-lambert
.PHONY: pdf figures scan-fast animation audit audit-posix-legacy clean
.PHONY: o2-gr o4-mga o6-interactive o7-parallel o7-surrogate bonus-all

# ---- Default: compile + generate figures + build PDF ----
all: compile m3 figures animation m5-fair m5-lambert pdf
	@echo "=== all: compile + m3 + figures + animation + pdf done ==="
	@echo "  -> $(words $(REPORT_IMAGES)) figures found in data/results/"

# ---- Syntax check ----
compile:
	@echo "=== Compiling src/ ==="
	$(PYTHON) -m compileall src
	@echo "Compilation OK"

# ---- Full regression (runs all m1-m8, ~10 min) ----
validate: compile
	@echo "=== Running all regression tests ==="
	cd src && $(PYTHON) validation.py --case all
	@echo "Validation complete"

m1: ; cd src && $(PYTHON) validation.py --case m1
m2: ; cd src && $(PYTHON) validation.py --case m2
m3: ; cd src && $(PYTHON) validation.py --case m3
m4: ; cd src && $(PYTHON) validation.py --case m4
m5: ; cd src && $(PYTHON) validation.py --case m5
m6: ; cd src && $(PYTHON) validation.py --case m6
m7: ; cd src && $(PYTHON) validation.py --case m7
m8: ; cd src && $(PYTHON) validation.py --case m8

validate-m3: compile
	@echo "=== M3 quick validation ==="
	cd src && $(PYTHON) validation.py --case m3
	@echo "M3 validation complete"

validate-m4: compile
	@echo "=== M4 quick validation ==="
	cd src && $(PYTHON) validation.py --case m4
	@echo "M4 validation complete"

# ---- M5 no-lunar baselines ----
m5-fair:
	@echo "=== M5: SOI-exit tangent baseline ==="
	cd src && $(PYTHON) experiments/m5_fair_no_lunar_baseline.py
	@echo "M5 fair done"

m5-lambert:
	@echo "=== M5: Lambert Earth-to-Earth baseline ==="
	cd src && $(PYTHON) experiments/m5_no_lunar_lambert_baseline.py
	@echo "M5 Lambert done"

validate-m5: m5-fair m5-lambert
	@echo "=== M5 validation complete ==="

# ---- O3/O3+/O4+: Differential and MGA correctors (optional) ----
o3:
	cd src && $(PYTHON) experiments/o3_differential_corrector.py
o3plus:
	cd src && $(PYTHON) experiments/o3plus_vector_differential_corrector.py
o4plus:
	cd src && $(PYTHON) experiments/o4plus_powered_mga_optimizer.py

# ---- PDF report (2 xelatex passes) ----
pdf:
	@echo "=== Building report.pdf ==="
	xelatex -interaction=nonstopmode -output-directory=. report.tex || true
	xelatex -interaction=nonstopmode -output-directory=. report.tex || true
	@echo "report.pdf built"

# ---- Generate M8 figures ----
figures: compile
	@echo "=== Generating M8 figures ==="
	cd src && $(PYTHON) validation.py --case m8
	@echo "Figures saved to data/results/"

# ---- Orbit animation (O5) ----
animation: figures
	@echo "=== Generating orbit animation ==="
	cd src && $(PYTHON) animation.py
	@echo "Animation saved to build/"

# ---- Optional extensions ----
o1-3d:
	@echo "=== O1: 3D vs 2D comparison ==="
	cd src && $(PYTHON) experiments/o1_3d_comparison.py
o2-gr:
	@echo "=== O2: GR correction ==="
	cd src && $(PYTHON) experiments/o2_relativity.py
o4-ephem:
	@echo "=== O4: extend ephemeris with Venus ==="
	cd src && $(PYTHON) experiments/o4_ephemeris_extend.py
o4-mga:
	@echo "=== O4: multi-gravity assist ==="
	cd src && $(PYTHON) experiments/o4_multi_gravity_assist.py
o6-interactive:
	@echo "=== O6: interactive demo screenshot ==="
	cd src && $(PYTHON) interactive_demo.py --screenshot
o7-parallel:
	@echo "=== O7: parallel scan (ProcessPool) ==="
	cd src && $(PYTHON) experiments/o7_parallel_scan.py

o7-surrogate:
	@echo "=== O7: Ridge surrogate prefilter ==="
	cd src && $(PYTHON) -c "import sys; sys.path.insert(0,'.'); from experiments.o7_surrogate_prefilter import main; main()"

o7-benchmark:
	@echo "=== O7: repeated benchmark (3 runs) ==="
	cd src && $(PYTHON) experiments/o7_parallel_scan.py --repeat 3

bonus-all: o1-3d o2-gr o3 o3plus o4-mga o4plus animation o6-interactive o7-parallel o7-surrogate
	@echo "=== All optional extensions complete ==="
# ---- Delta-v / baseline diagnostics (do not replace M1-M8) ----
delta-v-audit:
	@echo "=== Delta-v budget unified audit ==="
	cd src && $(PYTHON) delta_v_budget.py --self-test
m5-global-baseline:
	@echo "=== M5 global no-lunar baseline diagnostic ==="
	cd src && $(PYTHON) experiments/m5_global_no_lunar_baseline.py
m6-pareto:
	@echo "=== M6 Pareto window diagnostic ==="
	cd src && $(PYTHON) experiments/m6_pareto_window_diagnostic.py
figure-manifest:
	@echo "=== Generating figure manifest ==="
	cd src && $(PYTHON) experiments/generate_figure_manifest.py

test:
	@echo "=== Unit tests ==="
	$(PYTHON) -m unittest discover -s tests

numerical-audit:
	@echo "=== Numerical correctness audit ==="
	cd src && $(PYTHON) experiments/numerical_correctness_audit.py

m6-complete-window-search:
	@echo "=== M6 complete-return window search ==="
	cd src && $(PYTHON) experiments/m6_complete_return_window_search.py

m6-legal-window-search:
	@echo "=== M6 legal-window derived search ==="
	cd src && $(PYTHON) experiments/m6_complete_return_window_search.py --mode derived-legal-window

m6-independent-window-search:
	@echo "=== M6 legal-window independent search ==="
	cd src && $(PYTHON) experiments/m6_independent_window_search.py

m6-deep-audit:
	@echo "=== M6 numerical deep audit ==="
	cd src && $(PYTHON) experiments/m6_numerical_deep_audit.py

m6-independent-spotcheck:
	@echo "=== M6 independent spotcheck ==="
	cd src && $(PYTHON) experiments/m6_independent_spotcheck.py

check-m6-return-semantics:
	@echo "=== Check M6 return-event semantics ==="
	cd src && $(PYTHON) experiments/check_m6_return_semantics.py

m3-deep-audit:
	@echo "=== M3 numerical deep audit ==="
	cd src && $(PYTHON) experiments/m3_numerical_deep_audit.py

check-m3-horizons-semantics:
	@echo "=== Check M3 Horizons semantics ==="
	cd src && $(PYTHON) experiments/check_m3_horizons_semantics.py

schema-check:
	@echo "=== Schema check ==="
	cd src && $(PYTHON) experiments/check_result_schemas.py

quick-check: compile delta-v-audit figure-manifest schema-check test
	@echo "=== Quick engineering check complete ==="

m5-fresh-repro-test:
	@echo "=== M5 fresh reproducibility guard ==="
	cd src && $(PYTHON) experiments/check_m5_fresh_reproducibility.py

repair-m5:
	@echo "=== M5 fair saving ratio search ==="
	cd src && $(PYTHON) experiments/m5_fair_saving_ratio_search.py

repair-m5-real-fast:
	@echo "=== M5 saving ratio (fast — requires existing legal-window JSON) ==="
	cd src && $(PYTHON) experiments/m5_fixed_date_current_compare.py
	cd src && $(PYTHON) experiments/m5_saving_ratio_resolver.py

repair-m5-real:
	@echo "=== M5 complete pipeline: legal-window lunar anchor + same-date no-lunar DSM + saving ratio ==="
	cd src && $(PYTHON) experiments/m5_lunar_return_local_refine.py
	cd src && $(PYTHON) experiments/m5_best_lunar_candidate_verify.py
	cd src && $(PYTHON) experiments/m5_no_lunar_fixed_date_deep_search.py
	cd src && $(PYTHON) experiments/m5_fixed_date_current_compare.py
	cd src && $(PYTHON) experiments/m5_same_window_lunar_no_lunar_pareto.py
	cd src && $(PYTHON) experiments/m5_saving_ratio_resolver.py
return-event-audit:
lunar-return-local-refine:
	@echo "=== M5 lunar return local refine ==="
	cd src && $(PYTHON) experiments/m5_lunar_return_local_refine.py

complete-lunar-return-search:
	@echo "=== Complete lunar return search (M5 + M6) ==="
	cd src && $(PYTHON) experiments/m5_complete_lunar_return_search.py
	cd src && $(PYTHON) experiments/m6_complete_lunar_return_search.py
	cd src && $(PYTHON) experiments/m5_saving_ratio_resolver.py

m5-lunar-best-fixed-date-compare:
	@echo "=== M5 best lunar fixed-date comparison ==="
	cd src && $(PYTHON) experiments/m5_best_lunar_candidate_verify.py
	cd src && $(PYTHON) experiments/m5_fixed_date_no_lunar_for_lunar_best.py
	cd src && $(PYTHON) experiments/m5_fixed_date_lunar_vs_no_lunar_t61037.py

m5-t61037-deep-compare:
	@echo "=== M5 t0=61037 deep no-lunar + comparison ==="
	cd src && $(PYTHON) experiments/m5_no_lunar_t61037_deep_search.py
	cd src && $(PYTHON) experiments/m5_t61037_lunar_vs_no_lunar_deep_compare.py

m5-same-window-pareto:
	@echo "=== M5 same-window lunar vs no-lunar Pareto ==="
	cd src && $(PYTHON) experiments/m5_same_window_lunar_no_lunar_pareto.py

lunar-return-completion:
	@echo "=== Lunar return completion (M5 + M6) ==="
	cd src && $(PYTHON) experiments/m5_lunar_return_completion.py
	cd src && $(PYTHON) experiments/m5_lunar_completed_vs_no_lunar.py
	cd src && $(PYTHON) experiments/m6_lunar_return_completion.py

check-invalidated-results:
	@echo "=== Check invalidated formal results ==="
	cd src && $(PYTHON) experiments/check_invalidated_formal_results.py

return-semantics-test:
	@echo "=== Event semantics unit tests ==="
	$(PYTHON) -m unittest tests.test_event_semantics
	@echo "=== Return event audit (M5 + M6 lunar) ==="
	cd src && $(PYTHON) experiments/m5_lunar_return_event_audit.py
	cd src && $(PYTHON) experiments/m6_lunar_return_event_audit.py

m5-budget-sensitivity:
	@echo "=== M5 budget sensitivity analysis ==="
	cd src && $(PYTHON) experiments/m5_budget_sensitivity.py

repair-m6:
	@echo "=== M6 constrained window refine ==="
	cd src && $(PYTHON) experiments/m6_constrained_window_refine.py

repair-m3:
	@echo "=== M3 residual improvement ==="
	cd src && $(PYTHON) experiments/m3_residual_improvement.py

repair-m3-actual:
	@echo "=== M3 model hierarchy (3-body / 5-body / full planetary) ==="
	cd src && $(PYTHON) experiments/m3_model_hierarchy.py

m3-hierarchy:
	@echo "=== M3 model hierarchy ==="
	cd src && $(PYTHON) experiments/m3_model_hierarchy.py

repair-m6-actual:
	@echo "=== M6 actual constrained search (no proxy) ==="
	cd src && $(PYTHON) experiments/m6_actual_constrained_search.py

repair-m7:
	@echo "=== M7 extended MC (200 samples) ==="
	cd src && $(PYTHON) experiments/m7_extended_monte_carlo.py --n 200 --seed 202606 --save-sample-rows --output ../data/results/m7_extended_monte_carlo.json

m7-mc-profile:
	@echo "=== M7 MC profile (n=20) ==="
	cd src && $(PYTHON) experiments/m7_extended_monte_carlo.py --n 20 --seed 202606 --profile --output ../data/results/m7_extended_monte_carlo_profile.json

m7-mc-smoke:
	@echo "=== M7 MC smoke (n=20) ==="
	cd src && $(PYTHON) experiments/m7_extended_monte_carlo.py --n 20 --seed 202606 --smoke --output ../data/results/m7_extended_monte_carlo_smoke.json

m7-mc-full:
	@echo "=== M7 MC full (n=200) ==="
	cd src && $(PYTHON) experiments/m7_extended_monte_carlo.py --n 200 --seed 202606 --save-sample-rows --output ../data/results/m7_extended_monte_carlo.json

m7-timeout-replay:
	@echo "=== M7 timeout replay ==="
	cd src && $(PYTHON) experiments/m7_timeout_replay.py

check-m7-return-semantics:
	@echo "=== Check M7 return-event semantics ==="
	cd src && $(PYTHON) experiments/check_m7_return_semantics.py

benchmark-return-audit:
	@echo "=== Return v_inf frame/energy audit ==="
	cd src && $(PYTHON) experiments/return_vinf_frame_energy_audit.py

benchmark-m3-leakage:
	@echo "=== M3 Horizons leakage/independence audit ==="
	cd src && $(PYTHON) experiments/m3_horizons_leakage_audit.py

benchmark-audit:
	$(MAKE) benchmark-return-audit
	$(MAKE) benchmark-m3-leakage

polish-diagnostics: delta-v-audit m5-global-baseline m6-pareto
	@echo "=== Polish diagnostics complete ==="
# ---- Fast geometric launch-window scan (M6) ----
scan-fast:
	@echo "=== Running fast window scan (M6) ==="
	cd src && $(PYTHON) validation.py --case m6
	@echo "Window scan done — see data/results/m6_regression.json"

# ---- Comprehensive audit ----
audit:
	@echo "=== Portable audit ==="
	$(PYTHON) src/experiments/portable_audit.py

audit-posix-legacy:
	@echo "=== Audit check ==="
	@echo ""
	@echo "--- Security ---"
	@git ls-files config/ 2>/dev/null | grep -q . && echo "  WARNING: config/ is tracked!" || echo "  [OK] config/ is gitignored"
	@git grep -l "fce2a741a94feded5c3b9b7ab51f6748" 2>/dev/null | grep -v Makefile > /dev/null && echo "  WARNING: token in tracked files!" || echo "  [OK] no token leaks"
	@echo ""
	@echo "--- Large files (>5 MB) ---"
	@if [ -n "$$(find . -size +5M -not -path './.git/*' 2>/dev/null | head -5)" ]; then echo "  WARNING: large files!"; find . -size +5M -not -path "./.git/*" 2>/dev/null | head -5; else echo "  [OK] no files >5 MB"; fi
	@echo ""
	@echo "--- Repo size ---"
	@du -sh . | awk '{print "  " $$1}'
	@echo ""
	@echo "--- Figure reference check (report.tex -> data/results/) ---"
	@missing=0; \
	for img in $$(grep -oP 'data/results/[^}]*\.png' report.tex 2>/dev/null); do \
		if [ -f "$$img" ]; then echo "  [OK] $$img"; else echo "  [MISS] $$img"; missing=$$((missing+1)); fi; \
	done; \
	if [ $$missing -eq 0 ]; then echo "  All figures present."; else echo "  WARNING: $$missing figure(s) missing!"; fi
	@echo ""
	@echo "--- M5 result files ---"
	@for f in data/results/m5_fair_no_lunar_baseline.json data/results/m5_fair_no_lunar_baseline.csv data/results/m5_no_lunar_lambert_baseline.json data/results/m5_no_lunar_lambert_baseline.csv data/results/m5_no_lunar_lambert_pareto_t061066.json data/results/m5_no_lunar_lambert_pareto.png data/results/m5_no_lunar_lambert_pareto_t061154.json; do \
		if [ -f "$$f" ]; then echo "  [OK] $$f"; else echo "  [MISS] $$f"; fi; \
	done
	@echo ""
	@echo "--- Git status ---"
	@git status --short
	@echo ""
	@echo "Audit complete"

# ---- Clean ----
clean:
	$(PYTHON) src/experiments/portable_clean.py
