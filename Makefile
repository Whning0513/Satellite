# MSPJ Final Project — Makefile
#
# Targets:
#   all        — default: compile + figures + pdf
#   compile    — python -m compileall src (syntax check)
#   validate   — run all regression tests (m1-m8)
#   validate-m3 — run M3 regression only
#   validate-m4 — run M4 regression only
#   pdf        — build report.pdf via xelatex
#   figures    — generate all M8 figures (requires m3 residuals)
#   animation  — generate orbit animation MP4/GIF (not in default all)
#   scan-fast  — fast geometric launch-window scan (M6)
#   m1..m8     — run individual regression test cases
#   o3         — test shooting corrector
#   audit      — security + figure-reference + repo-size check
#   clean      — remove cache / build artifacts
#
# Usage:
#   make all       — full build from clean checkout
#   make figures   — only regenerate plots
#   make pdf       — only rebuild report.pdf
#   make validate  — run all regression tests
#   make clean     — remove generated files

SHELL := /bin/bash
PYTHON := python
REPORT_IMAGES := $(wildcard data/results/m8_*.png)

.PHONY: all compile validate validate-m3 validate-m4
.PHONY: m1 m2 m3 m4 m5 m6 m7 m8 o3
.PHONY: pdf figures scan-fast animation audit clean

# ---- Default: compile + generate figures + build PDF ----
# NOTE: validate (all milestones) is NOT in all because it's heavy (~10 min).
# Run 'make validate' separately before submission.
all: compile figures pdf
	@echo "=== all: compile + figures + pdf done ==="
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

# ---- Individual milestone targets ----
# Each calls validation.py with the specific case.
# These are lightweight and can be run independently.
m1:
	cd src && $(PYTHON) validation.py --case m1

m2:
	cd src && $(PYTHON) validation.py --case m2

m3:
	cd src && $(PYTHON) validation.py --case m3

m4:
	cd src && $(PYTHON) validation.py --case m4

m5:
	cd src && $(PYTHON) validation.py --case m5

m6:
	cd src && $(PYTHON) validation.py --case m6

m7:
	cd src && $(PYTHON) validation.py --case m7

m8:
	cd src && $(PYTHON) validation.py --case m8

# ---- Explicit validate-m3 / validate-m4 (quick checks) ----
validate-m3: compile
	@echo "=== M3 quick validation ==="
	cd src && $(PYTHON) validation.py --case m3
	@echo "M3 validation complete"

validate-m4: compile
	@echo "=== M4 quick validation ==="
	cd src && $(PYTHON) validation.py --case m4
	@echo "M4 validation complete"

# ---- O3: Shooting corrector (optional) ----
o3:
	cd src && $(PYTHON) shooting_corrector.py

# ---- PDF report (2 xelatex passes) ----
pdf:
	@echo "=== Building report.pdf ==="
	xelatex -interaction=nonstopmode -output-directory=. report.tex
	xelatex -interaction=nonstopmode -output-directory=. report.tex
	@echo "report.pdf built"

# ---- Generate M8 figures (requires m3 residuals) ----
figures: compile
	@echo "=== Generating M8 figures ==="
	cd src && $(PYTHON) validation.py --case m8
	@echo "Figures saved to data/results/"

# ---- Generate orbit animation (O5, not in default all) ----
animation: figures
	@echo "=== Generating orbit animation ==="
	cd src && $(PYTHON) animation.py
	@echo "Animation saved to data/results/"

# ---- Fast geometric launch-window scan (M6, ~60s) ----
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
		if [ -f "$$img" ]; then \
			echo "  [OK] $$img"; \
		else \
			echo "  [MISS] $$img"; \
			missing=$$((missing+1)); \
		fi; \
	done; \
	if [ $$missing -eq 0 ]; then echo "  All figures present."; else echo "  WARNING: $$missing figure(s) missing!"; fi
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
