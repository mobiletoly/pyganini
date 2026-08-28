# Pyganini foundation probes

This standalone uv project records executable evidence for Pyganini foundation
decisions. It is not a Pyganini package, and its module names, fixtures, generated
shapes, and helper interfaces are not public contracts.

Run the locked checks from this directory:

```text
uv sync --locked --python 3.14
uv run --locked --python 3.14 ruff format --check .
uv run --locked --python 3.14 ruff check .
uv run --locked --python 3.14 mypy foundation_probes tests
uv run --locked --python 3.14 pyright foundation_probes tests
uv run --locked --python 3.14 pytest
uv sync --locked --python 3.13
uv run --locked --python 3.13 pytest
```

The repository-level child specification owns the complete validation and
cleanup sequence. Do not import this project from future production packages.
