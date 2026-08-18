.PHONY: help install dev lint format test clean config

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install:  ## Install the package (auto-detects root, uv, pipx, or pip)
	@if [ "$$(id -u)" = "0" ]; then \
		echo "Running as root, installing system-wide..."; \
		pip install .; \
	elif command -v uv >/dev/null 2>&1; then \
		echo "Installing with uv..."; \
		uv tool install .; \
	elif command -v pipx >/dev/null 2>&1; then \
		echo "Installing with pipx..."; \
		pipx install .; \
	else \
		echo "Tip: Install uv or pipx for isolated installs (pacman -S uv, apt install pipx, brew install uv)"; \
		echo "Falling back to pip install --user ..."; \
		PIP_BREAK_SYSTEM_PACKAGES=1 pip install --user .; \
	fi

dev:  ## Install with dev dependencies (editable) and set up the git hooks
	PIP_BREAK_SYSTEM_PACKAGES=1 pip install -e ".[dev]"
	python -m pre_commit install
	python -m pre_commit install --hook-type pre-push
	python -m pre_commit install --hook-type commit-msg

config:  ## Copy the example config into place, if there is none yet
	@dest="$${XDG_CONFIG_HOME:-$$HOME/.config}/boattracker/config.toml"; \
	if [ -e "$$dest" ]; then \
		echo "$$dest already exists, leaving it alone"; \
	else \
		mkdir -p "$$(dirname "$$dest")"; \
		cp config.example.toml "$$dest"; \
		echo "Wrote $$dest — every setting in it is commented out, i.e. defaults."; \
	fi

lint:  ## Run ruff
	python -m ruff check .

# Deliberately not `ruff format` — see the comment at the top of .pre-commit-config.yaml.
format:  ## Apply ruff's own fixes (lint fixes only, no reformatting)
	python -m ruff check --fix .

test:  ## Run the test suite
	python -m pytest

clean:  ## Remove build artifacts
	rm -rf dist/ build/ *.egg-info src/*.egg-info .pytest_cache .ruff_cache .lycheecache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
