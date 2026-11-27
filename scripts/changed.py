# SPDX-License-Identifier: LGPL-2.1-or-later

"""Say whether a change since `base` reaches past some dependency groups.

    python -m scripts.changed BASE "lint docs"

Prints `false` when the only file changed is `pyproject.toml`, and only in
the groups named; `true` otherwise.
"""

from __future__ import annotations

import argparse
import subprocess
from typing import Any

import tomllib

MANIFEST = "pyproject.toml"


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], check=True, capture_output=True, text=True
    ).stdout


def _without(manifest: str, groups: list[str]) -> dict[str, Any]:
    parsed = tomllib.loads(manifest)
    kept = parsed.get("dependency-groups", {})
    parsed["dependency-groups"] = {
        name: value for name, value in kept.items() if name not in groups
    }
    return parsed


def reaches_past(base: str, groups: list[str]) -> bool:
    """Whether the change from `base` to HEAD is more than `groups`."""
    files = _git("diff", "--name-only", f"{base}...HEAD").split()
    if files != [MANIFEST]:
        return True
    before = _git("show", f"{base}:{MANIFEST}")
    after = _git("show", f"HEAD:{MANIFEST}")
    return _without(before, groups) != _without(after, groups)


def main() -> None:
    """Print the answer for the base and groups the command line names."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base")
    parser.add_argument("groups", type=str.split)
    arguments = parser.parse_args()
    print(str(reaches_past(arguments.base, arguments.groups)).lower())


if __name__ == "__main__":
    main()
