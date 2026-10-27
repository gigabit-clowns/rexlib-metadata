# SPDX-License-Identifier: LGPL-2.1-or-later

from collections.abc import Sequence
from typing import Any

def version() -> str: ...
def _star_read_tables(path: str) -> Sequence[tuple[str, Any]]: ...
