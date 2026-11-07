.PHONY: install project run build lint format test typecheck check demo publish

install:
	uv sync --locked

project run:
	uv run valutatrade

build:
	uv build

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

test:
	uv run python -m unittest discover -s tests -v

typecheck:
	uv run mypy valutatrade_hub tests demo

check: lint typecheck test

demo:
	uv run python demo/record.py

publish: build
	uv publish
