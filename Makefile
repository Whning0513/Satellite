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
#   o1-3d, o2-gr, o4-mga, o6-interactive, o7-parallel — optional extensions
#   bonus-all  — all optional extensions
#   audit      — security + figure-reference + M5-files + repo-size check
#   clean      — remove cache / build artifacts

SHELL := /bin/bash
PYTHON := python
REPORT_IMAGES := $(wildcard data/results/m8_*.png)

.PHONY: all compile validate validate-m3 validate-m4 validate-m5
.PHONY: m1 m2 m3 m4 m5 m6 m7 m8 o3 o1-3d m5-fair m5-lambert
.PHONY: pdf figures scan-fast animation audit clean
.PHONY: o2-gr o4-mga o6-interactive o7-parallel bonus-all

# ---- Default: compile + generate figures + build PDF ----
all: compile m3 figures m5-lambert pdf
	@echo "=== all: compile + m3 + figures + pdf done ==="
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

# ---- O3: Shooting corrector (optional) ----
o3:
	cd src && $(PYTHON) shooting_corrector.py

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
o4-mga:
	@echo "=== O4: multi-gravity assist ==="
	cd src && $(PYTHON) experiments/o4_multi_gravity_assist.py
o6-interactive:
	@echo "=== O6: interactive demo screenshot ==="
	cd src && $(PYTHON) interactive_demo.py --screenshot
o7-parallel:
	@echo "=== O7: parallel scan ==="
	cd src && $(PYTHON) experiments/o7_parallel_scan.py

bonus-all: o1-3d o2-gr o3 o4-mga animation o6-interactive o7-parallel
	@echo "=== All optional extensions complete ==="

# ---- Fast geometric launch-window scan (M6) ----
scan-fast:
	@echo "=== Running fast window scan (M6) ==="
	cd src && $(PYTHON) validation.py --case m6
	@echo "Window scan done — see data/results/m6_regression.json"

# ---- Comprehensive audit ----
audit:
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
	@for f in data/results/m5_fair_no_lunar_baseline.json data/results/m5_fair_no_lunar_baseline.csv data/results/m5_no_lunar_lambert_baseline.json data/results/m5_no_lunar_lambert_baseline.csv data/results/m5_no_lunar_lambert_pareto.json data/results/m5_no_lunar_lambert_pareto.png; do \
		if [ -f "$$f" ]; then echo "  [OK] $$f"; else echo "  [MISS] $$f"; fi; \
	done
	@echo ""
	@echo "--- Git status ---"
	@git status --short
	@echo ""
	@echo "Audit complete"

# ---- Clean ----
clean:
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -name "*.pyc" -delete
	@rm -f report.aux report.log report.out report.toc report.pdf
	@rm -f data/results/*.png data/results/*.gif data/results/*.json 2>/dev/null; true
	@rm -rf src/__pycache__ 2>/dev/null; true
	@echo "Cleaned __pycache__, .pyc, LaTeX artifacts, and data/results/"
