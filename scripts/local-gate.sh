#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

candidates=(".venv/bin/python" ".venv/Scripts/python.exe")
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    candidates=("$VIRTUAL_ENV/bin/python" "$VIRTUAL_ENV/Scripts/python.exe" "${candidates[@]}")
fi
python=""
for candidate in "${candidates[@]}"; do
    if [[ -x "$candidate" ]]; then
        python="$candidate"
        break
    fi
done
if [[ -z "$python" ]]; then
    echo "No virtual environment found. Activate one, or make it .venv/." >&2
    exit 1
fi

bin="$(dirname "$python")"

step() {
    printf '\n\033[1m==> %s\033[0m\n' "$1"
    shift
    "$@"
}

step "cargo fmt" cargo fmt --check
step "cargo build" cargo build --locked
step "cargo test" cargo test --locked
step "cargo clippy" cargo clippy --locked --all-targets -- -D warnings
step "maturin develop" "$python" -m maturin develop --quiet
step "ruff" "$python" -m ruff check .
step "ruff format" "$python" -m ruff format --check .
step "complexipy" "$bin/complexipy" python tests benchmarks scripts --max-complexity-allowed 7 --quiet
step "mypy" "$python" -m mypy
step "pytest" "$python" -m pytest tests/python/
step "cargo doc" env RUSTDOCFLAGS="-D warnings" \
    cargo doc --locked --no-deps --document-private-items --quiet
site="$(mktemp -d)"
trap 'rm -rf "$site"' EXIT
step "docs" "$python" -W error -m scripts.docs "$site"

printf '\n\033[1mThe gate is green.\033[0m\n'
