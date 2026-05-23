.PHONY: install dev test lint format clean run-demo

PYTHON = python3
PIP = pip3

install:
	$(PIP) install -r requirements.txt

dev:
	$(PIP) install -e ".[dev]"

test:
	cd . && . .venv/bin/activate && pytest -q

lint:
	ruff check memoryx/ tests/ 2>/dev/null || true

format:
	black memoryx/ tests/ 2>/dev/null || true

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type d -name .pytest_cache -exec rm -rf {} +

run-demo:
	$(PYTHON) -c "from memoryx import MemoryHookManager; print('memoryx loaded')"
