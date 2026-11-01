# SPDX-License-Identifier: LGPL-2.1-or-later

from pathlib import Path

import pyarrow as pa
import pytest

from rexlib_metadata._arrow import ArrowArrayExportable, to_pyarrow_table
from rexlib_metadata._rexlib import _star_read_chunks, _star_read_tables

MINI = Path(__file__).parent / "fixtures" / "mini.star"


def first_batch():
    _, batches = _star_read_tables(str(MINI))[0]
    return batches[0]


def test_what_rust_hands_back_speaks_the_protocol_the_stub_promises():
    assert isinstance(first_batch(), ArrowArrayExportable)


def test_a_batch_crosses_over_as_a_pyarrow_table():
    table = to_pyarrow_table([first_batch()])

    assert isinstance(table, pa.Table)
    assert table.num_rows == 3


def test_chunks_cross_over_a_few_rows_at_a_time():
    chunks = list(_star_read_chunks(str(MINI), 2))

    assert [name for name, _, _ in chunks] == ["particles", "particles"]
    assert [to_pyarrow_table([c]).num_rows for _, _, c in chunks] == [2, 1]
    assert all(isinstance(c, ArrowArrayExportable) for _, _, c in chunks)


def test_every_chunk_says_which_block_it_came_from():
    chunks = list(_star_read_chunks(str(MINI), 2))

    assert [ordinal for _, ordinal, _ in chunks] == [0, 0]


def test_chunks_carry_only_the_columns_asked_for():
    ((_, _, chunk),) = _star_read_chunks(str(MINI), 10, {"_rlnAngleTilt"})

    assert to_pyarrow_table([chunk]).column_names == ["_rlnAngleTilt"]


def test_chunks_that_ran_out_stay_out():
    chunks = _star_read_chunks(str(MINI), 10)
    list(chunks)

    assert next(chunks, None) is None


def test_a_chunk_of_no_rows_is_refused():
    with pytest.raises(ValueError, match="at least one row"):
        _star_read_chunks(str(MINI), 0)


def test_a_missing_file_is_found_missing_when_chunks_are_asked_for(tmp_path):
    with pytest.raises(FileNotFoundError):
        _star_read_chunks(str(tmp_path / "missing.star"), 10)
