# Waseller — make targets (espejo del CI gate)
.PHONY: help dev check lint format typecheck test build twine clean

PKG := sdk/waseller
SRC := sdk/waseller services tests

help:
	@echo "Waseller — make targets"
	@echo "  dev        Install -e .[dev]"
	@echo "  check      Gate completo: lint + typecheck + test (lo que corre el CI)"
	@echo "  lint       ruff check + ruff format --check"
	@echo "  format     ruff --fix + ruff format (autofix)"
	@echo "  typecheck  mypy --strict sobre $(SRC)"
	@echo "  test       pytest -m 'not integration'"
	@echo "  build      python -m build (sdist + wheel en dist/)"
	@echo "  twine      twine check dist/* (validación pre-PyPI)"
	@echo "  clean      Limpia caches y dist"

dev:
	python -m pip install -e ".[dev]"

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

typecheck:
	mypy $(SRC)

test:
	pytest -m "not integration"

check: lint typecheck test
	@echo "All gates passed."

build: clean
	python -m build

twine: build
	twine check dist/*

clean:
	python -c "import shutil, glob; [shutil.rmtree(p, ignore_errors=True) for p in glob.glob('**/__pycache__', recursive=True) + ['.mypy_cache', '.ruff_cache', '.pytest_cache', 'dist', 'build']]"
