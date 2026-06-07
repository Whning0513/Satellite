# MSPJ Final Project — Makefile
#
# Targets:
#   all        — default: compile + pdf
#   compile    — python -m compileall src (syntax check)
#   validate   — run all regression tests
#   pdf        — build report.pdf via xelatex
#   figures    — generate all M8 figures
#   animation  — generate orbit animation MP4/GIF
#   scan-fast  — fast geometric launch-window scan (M6)
#   m1..m8     — run individual regression test cases
#   o3         — test shooting corrector
#   audit      — security check: no credentials in tracked files
#   clean      — remove cache / build artifacts

SHELL := /bin/bash
PYTHON := python

.PHONY: all compile validate pdf figures scan-fast animation audit
.PHONY: m1 m2 m3 m4 m5 m6 m7 m8 o3 clean

# ---- Default ----
all: compile pdf
	@echo "=== all: compile + pdf done ==="

# ---- Syntax check ----
compile:
	@echo "=== Compiling src/ ==="
	$(PYTHON) -m compileall src
	@echo "Compilation OK"

# ---- Full regression ----
validate: compile
	@echo "=== Running all regression tests ==="
	cd src && $(PYTHON) validation.py --case all
	@echo "Validation complete"

# ---- Individual milestones ----
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

# ---- O3: Shooting corrector ----
o3:
	cd src && $(PYTHON) shooting_corrector.py

# ---- PDF report ----
pdf:
	@echo "=== Building report.pdf ==="
	xelatex -interaction=nonstopmode -output-directory=. report.tex
	xelatex -interaction=nonstopmode -output-directory=. report.tex
	@echo "report.pdf built"

# ---- Generate M8 figures (fast, ~30s) ----
figures:
	@echo "=== Generating M8 figures ==="
	cd src && $(PYTHON) validation.py --case m8
	@echo "Figures saved to data/results/"

# ---- Generate orbit animation (O5) ----
animation: figures
	@echo "=== Generating orbit animation ==="
	cd src && $(PYTHON) animation.py
	@echo "Animation saved to data/results/"

# ---- Fast geometric launch-window scan (M6, ~60s) ----
scan-fast:
	@echo "=== Running fast window scan (M6) ==="
	cd src && $(PYTHON) validation.py --case m6
	@echo "Window scan done — see data/results/m6_regression.json"

# ---- Security audit: ensure credentials not in tracked files ----
audit:
	@echo "=== Security audit ==="
	@echo "  Checking for config/proxy.ini in tracked files..."
	@git ls-files config/ 2>/dev/null | grep -q . && echo "  WARNING: config/ is tracked!" || echo "  OK: config/ is gitignored"
	@echo "  Checking for token in tracked Python files..."
	@git grep -l "fce2a741a94feded5c3b9b7ab51f6748" 2>/dev/null && echo "  WARNING: token found!" || echo "  OK: no token leaks"
	@echo "  Checking for large generated files..."
	@if [ -n "$$(find data/results -name '*.json' -size +500k 2>/dev/null | head -5)" ]; then echo "  WARNING: large JSONs!"; else echo "  OK: no large generated files"; fi
	@echo "Security audit complete"

# ---- Clean ----
clean:
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -name "*.pyc" -delete
	@rm -f report.aux report.log report.out report.toc report.pdf
	@rm -f data/results/*.png data/results/*.gif data/results/*.json 2>/dev/null; true
	@echo "Cleaned __pycache__, .pyc, LaTeX build artifacts, and generated outputs"
