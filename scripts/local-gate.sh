#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

python=""
for candidate in "${VIRTUAL_ENV:-}/bin/python" "${VIRTUAL_ENV:-}/Scripts/python.exe" \
    ".venv/bin/python" ".venv/Scripts/python.exe"; do
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
step "cargo build" cargo build
step "cargo test" cargo test
step "cargo clippy" cargo clippy --all-targets -- -D warnings
step "maturin develop" "$python" -m maturin develop --quiet
step "ruff" "$python" -m ruff check .
step "complexipy" "$bin/complexipy" python tests --max-complexity-allowed 7 --quiet
step "pytest" "$python" -m pytest tests/python/

printf '\n\033[1mThe gate is green.\033[0m\n'
