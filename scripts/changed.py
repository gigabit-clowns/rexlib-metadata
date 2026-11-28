# SPDX-License-Identifier: LGPL-2.1-or-later

"""Say whether `pyproject.toml` differs from another outside some groups.

    git show BASE:pyproject.toml | python -m scripts.changed "lint docs"

Prints `false` when the manifest read from standard input and the one here
differ only in the dependency groups named; `true` otherwise.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import tomllib

MANIFEST = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _without(manifest: str, groups: list[str]) -> dict[str, Any]:
    parsed = tomllib.loads(manifest)
    kept = parsed.get("dependency-groups", {})
    parsed["dependency-groups"] = {
        name: value for name, value in kept.items() if name not in groups
    }
    return parsed


def reaches_past(before: str, after: str, groups: list[str]) -> bool:
    """Whether the manifests `before` and `after` differ outside `groups`."""
    return _without(before, groups) != _without(after, groups)


def main() -> None:
    """Print the answer for the groups the command line names."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("groups", type=str.split)
    groups = parser.parse_args().groups
    before = sys.stdin.read()
    after = MANIFEST.read_text(encoding="utf-8")
    print(str(reaches_past(before, after, groups)).lower())


if __name__ == "__main__":
    main()
