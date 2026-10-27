# SPDX-License-Identifier: LGPL-2.1-or-later

from pathlib import Path

import pyarrow as pa

from rexlib_metadata._arrow import ArrowArrayExportable, to_pyarrow_table
from rexlib_metadata._rexlib import _star_read_tables

MINI = Path(__file__).parent / "fixtures" / "mini.star"


def first_batch():
    _, batch = _star_read_tables(str(MINI))[0]
    return batch


def test_what_rust_hands_back_speaks_the_protocol_the_stub_promises():
    assert isinstance(first_batch(), ArrowArrayExportable)


def test_a_batch_crosses_over_as_a_pyarrow_table():
    table = to_pyarrow_table(first_batch())

    assert isinstance(table, pa.Table)
    assert table.num_rows == 3
