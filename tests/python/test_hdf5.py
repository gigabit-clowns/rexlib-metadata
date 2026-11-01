# SPDX-License-Identifier: LGPL-2.1-or-later

import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest

import rexlib_metadata as rxm
from rexlib_metadata.convention import RawTable
from rexlib_metadata.conventions.hdf5 import Hdf5Reader, Hdf5Writer

h5py = pytest.importorskip("h5py")
np = pytest.importorskip("numpy")

STAR = Path(__file__).parent.parent / "files" / "star"


def columns_file(tmp_path, rows=5):
    path = tmp_path / "data.h5"
    with h5py.File(path, "w", track_order=True) as file:
        group = file.create_group("particles", track_order=True)
        group["image_index"] = np.arange(rows)
        group["defocus"] = np.linspace(1.0, 2.0, rows)
        group["path"] = np.array(
            [f"img_{i}.mrc" for i in range(rows)], dtype=h5py.string_dtype()
        )
        group["pose"] = np.zeros((rows, 3), dtype=np.float32)
    return str(path)


def compound_file(tmp_path):
    path = tmp_path / "data.h5"
    dtype = np.dtype(
        [("uid", "<u8"), ("blob/path", "S12"), ("shift", "<f4", (2,))]
    )
    values = np.array(
        [(1, b">J1/a.mrc", (0.5, 1.0)), (2, b">J1/b.mrc", (2.0, 3.0))],
        dtype=dtype,
    )
    with h5py.File(path, "w", track_order=True) as file:
        file.create_group("run")["particles"] = values
        file["note"] = np.arange(3)  # a lone dataset at the root is no table
        file["image"] = np.zeros((2, 2, 2))
    return str(path)


def test_a_group_of_columns_is_one_table(tmp_path):
    raw = rxm.read(columns_file(tmp_path)).raw

    assert raw.names == ("particles",)
    table = raw["particles"].tables()[0].table
    assert table.column_names == ["image_index", "defocus", "path", "pose"]
    assert table.schema.field("pose").type == pa.list_(pa.float32(), 3)
    assert table.column("path").to_pylist()[0] == "img_0.mrc"


def test_a_compound_dataset_is_one_table_named_for_its_path(tmp_path):
    raw = rxm.read(compound_file(tmp_path)).raw

    assert raw.names == ("run/particles",)
    table = raw["run/particles"].tables()[0].table
    assert table.column("blob/path").to_pylist() == [">J1/a.mrc", ">J1/b.mrc"]
    assert table.column("shift").to_pylist() == [[0.5, 1.0], [2.0, 3.0]]
    assert table.schema.field("uid").type == pa.uint64()


def test_columns_at_the_root_are_the_table_with_no_name(tmp_path):
    path = tmp_path / "root.h5"
    with h5py.File(path, "w") as file:
        file["a"] = np.arange(2)

    assert rxm.read(str(path)).raw.names == ("",)


def test_a_read_keeping_columns_reads_only_those(tmp_path):
    reader = Hdf5Reader()

    kept = reader.read_tables_keeping(compound_file(tmp_path), {"uid"})

    assert kept[0].schema.column_names == ("uid",)


def test_chunks_slice_the_datasets(tmp_path):
    chunks = list(Hdf5Reader().read_chunks(columns_file(tmp_path, rows=5), 2))

    assert [(at, t.table.num_rows) for at, t in chunks] == [
        (0, 2),
        (0, 2),
        (0, 1),
    ]
    whole = Hdf5Reader().read_tables(columns_file(tmp_path, rows=5))[0]
    assert pa.concat_tables([t.table for _, t in chunks]) == whole.table


def test_a_table_of_no_rows_is_one_empty_chunk(tmp_path):
    chunks = list(Hdf5Reader().read_chunks(columns_file(tmp_path, rows=0), 2))

    assert [(at, t.table.num_rows) for at, t in chunks] == [(0, 0)]


def test_what_was_read_writes_back_the_same(tmp_path):
    source = rxm.read(columns_file(tmp_path)).raw
    out = str(tmp_path / "out.hdf5")

    source.write(out)
    again = rxm.read(out).raw

    assert again.names == source.names
    assert again.tables()[0].table == source.tables()[0].table


def test_a_star_file_writes_as_groups_of_text(tmp_path):
    out = str(tmp_path / "out.h5")
    source = rxm.read(str(STAR / "rln3.1_data_style.star")).raw

    source.write(out)
    again = rxm.read(out).raw

    assert again.names == source.names
    pd.testing.assert_frame_equal(
        again["block_2"].to_pandas(), source["block_2"].to_pandas()
    )


def test_a_null_is_refused_since_a_dataset_cannot_hold_one(tmp_path):
    table = RawTable.of("t", pa.table({"n": pa.array([1, None])}))
    writer = Hdf5Writer()

    with pytest.raises(ValueError, match="holds nulls"):
        writer.write_tables(str(tmp_path / "out.h5"), [table])


def test_a_nameless_table_beside_others_is_refused(tmp_path):
    tables = [
        RawTable.of("", pa.table({"a": [1]})),
        RawTable.of("b", pa.table({"a": [1]})),
    ]
    writer = Hdf5Writer()

    with pytest.raises(ValueError, match="no name"):
        writer.write_tables(str(tmp_path / "out.h5"), tables)


def test_a_file_that_is_not_hdf5_says_so(tmp_path):
    path = tmp_path / "text.h5"
    path.write_text("not hdf5")
    reader = Hdf5Reader()

    with pytest.raises(ValueError, match="not an HDF5 file"):
        reader.read_tables(str(path))


def test_without_h5py_the_error_says_how_to_get_it(tmp_path, monkeypatch):
    path = columns_file(tmp_path)
    monkeypatch.setitem(sys.modules, "h5py", None)
    reader = Hdf5Reader()

    with pytest.raises(ImportError, match=r"rexlib-metadata\[hdf5\]"):
        reader.read_tables(path)


@pytest.mark.parametrize("order", [("a", "a/b"), ("a/b", "a")])
def test_a_table_inside_another_is_refused(tmp_path, order):
    tables = [RawTable.of(name, pa.table({"x": [1]})) for name in order]
    writer = Hdf5Writer()

    with pytest.raises(ValueError, match="inside table 'a'"):
        writer.write_tables(str(tmp_path / "out.h5"), tables)


def test_a_table_of_no_columns_is_refused(tmp_path):
    table = RawTable.of("t", pa.table({"x": [1]}).drop_columns(["x"]))
    writer = Hdf5Writer()

    with pytest.raises(ValueError, match="no columns"):
        writer.write_tables(str(tmp_path / "out.h5"), [table])


@pytest.mark.parametrize(
    "made",
    [
        pytest.param(columns_file, id="column-group"),
        pytest.param(compound_file, id="compound"),
    ],
)
def test_schemas_are_what_a_whole_read_holds(tmp_path, made):
    path = made(tmp_path)
    reader = Hdf5Reader()

    schemas = reader.read_schemas(path)

    assert schemas == [table.schema for table in reader.read_tables(path)]
