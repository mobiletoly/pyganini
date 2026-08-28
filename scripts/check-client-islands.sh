#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
temporary_root="$(mktemp -d)"
trap 'rm -rf "$temporary_root"' EXIT HUP INT TERM

for command_name in uv node npm git diff shasum find sort mktemp dirname rm; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "client-island check: missing required command: $command_name" >&2
    exit 1
  fi
done

node_major="$(node -p 'process.versions.node.split(".")[0]')"
node_minor="$(node -p 'process.versions.node.split(".")[1]')"
if (( node_major < 20 || (node_major == 20 && node_minor < 19) )); then
  echo "client-island check: Node 20.19 or newer is required" >&2
  exit 1
fi

for product_root in \
  "$repository_root/examples/react_island/assets/build" \
  "$repository_root/examples/react_island/assets/dist" \
  "$repository_root/examples/svelte_island/assets/build" \
  "$repository_root/examples/svelte_island/assets/dist"; do
  while IFS= read -r required_product; do
    repository_path="${required_product#"$repository_root/"}"
    if git -C "$repository_root" check-ignore -q "$repository_path"; then
      echo "client-island check: required product is ignored: $repository_path" >&2
      exit 1
    fi
  done < <(find "$product_root" -type f -print)
done

snapshot_generated() {
  local example_root="$1"
  local destination="$2"
  (
    cd "$example_root"
    find app/_pyganini assets/dist assets/.pyganini assets/pyganini_assets_gen.py \
      -type f -print |
      LC_ALL=C sort |
      while IFS= read -r generated_file; do
        shasum -a 256 "$generated_file"
      done
  ) >"$destination"
}

check_example() {
  local example_name="$1"
  local example_root="$repository_root/examples/$example_name"
  local rebuilt_root="$temporary_root/$example_name/build"
  local before="$temporary_root/$example_name.before"
  local after="$temporary_root/$example_name.after"

  echo "Checking $example_name"
  (
    cd "$example_root"
    uv sync --locked --python 3.14
    npm ci
    npm run check
    npm exec vite -- build --outDir "$rebuilt_root"
    diff -r assets/build "$rebuilt_root"

    uv run --locked --python 3.14 ruff format --check .
    uv run --locked --python 3.14 ruff check .
    uv run --locked --python 3.14 mypy app tests
    uv run --locked --python 3.14 pyright app tests
    uv run --locked --python 3.14 pytest -q
    uv run --locked --python 3.14 pyganini assets check
    uv run --locked --python 3.14 pyganini check

    snapshot_generated "$example_root" "$before"
    uv run --locked --python 3.14 pyganini generate
    uv run --locked --python 3.14 pyganini check
    uv run --locked --python 3.14 pyganini assets check
    snapshot_generated "$example_root" "$after"
    diff "$before" "$after"

    uv sync --locked --python 3.13
    uv run --locked --python 3.13 ruff format --check .
    uv run --locked --python 3.13 ruff check .
    uv run --locked --python 3.13 mypy app tests
    uv run --locked --python 3.13 pyright app tests
    uv run --locked --python 3.13 pytest -q
    uv run --locked --python 3.13 pyganini check
    uv run --locked --python 3.13 pyganini assets check
  )
}

check_example react_island
check_example svelte_island

export PLAYWRIGHT_BROWSERS_PATH="$repository_root/examples/.playwright"
"$repository_root/examples/react_island/node_modules/.bin/playwright" install chromium

(
  cd "$repository_root/examples/react_island"
  npm run test:browser
)
(
  cd "$repository_root/examples/svelte_island"
  npm run test:browser
)
