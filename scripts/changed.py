# SPDX-License-Identifier: LGPL-2.1-or-later

"""Say whether two manifests differ outside some dependency groups.

    python -m scripts.changed BEFORE AFTER "lint docs"

Prints `false` when `BEFORE` and `AFTER` differ only in the groups named;
`true` otherwise.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import tomllib


def _without(manifest: Path, groups: list[str]) -> dict[str, Any]:
    parsed = tomllib.loads(manifest.read_text(encoding="utf-8"))
    kept = parsed.get("dependency-groups", {})
    parsed["dependency-groups"] = {
        name: value for name, value in kept.items() if name not in groups
    }
    return parsed


def reaches_past(before: Path, after: Path, groups: list[str]) -> bool:
    """Whether `before` and `after` differ outside `groups`."""
    return _without(before, groups) != _without(after, groups)


def main() -> None:
    """Print the answer for the manifests and groups the command line names."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("groups", type=str.split)
    arguments = parser.parse_args()
    answer = reaches_past(arguments.before, arguments.after, arguments.groups)
    print(str(answer).lower())


if __name__ == "__main__":
    main()
