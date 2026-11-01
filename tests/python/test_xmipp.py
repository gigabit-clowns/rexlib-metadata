# SPDX-License-Identifier: LGPL-2.1-or-later

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest

import rexlib_metadata as rxm
from rexlib_metadata.convention import RawTable
from rexlib_metadata.formats.star import StarWriter

FILES = Path(__file__).parent.parent / "files" / "xmd"


def read(name):
    return rxm.read(str(FILES / name))


@pytest.mark.parametrize("name", ["c3_stk.xmd", "i222.xmd"])
def test_an_xmipp_file_is_read_without_being_told_what_it_is(name):
    result = read(name)

    assert result.names == ("particles",)
    assert result.raw.names == ("noname",)
    assert list(result["particles"].to_pandas().columns) == [
        "image_path",
        "image_index",
        "angle_rot",
        "angle_tilt",
        "angle_psi",
    ]


def test_an_xmipp_image_reference_counts_from_zero():
    df = read("c3_stk.xmd")["particles"].to_pandas()

    assert df["image_path"][0] == "c3_stk.mrc"
    assert df["image_index"].tolist() == list(range(10))


@pytest.mark.parametrize("name", ["c3_stk.xmd", "i222.xmd"])
def test_the_angles_are_the_ones_the_file_holds(name):
    result = read(name)
    raw = result.raw.to_pandas()
    df = result["particles"].to_pandas()

    assert df["angle_rot"].tolist() == raw["_angleRot"].astype(float).tolist()
    assert df["angle_psi"].tolist() == raw["_anglePsi"].astype(float).tolist()


def test_an_xmd_is_written_with_the_header_xmipp_looks_for(tmp_path):
    source = read("c3_stk.xmd")
    out = tmp_path / "out.xmd"

    source.write(str(out))
    again = rxm.read(str(out))

    assert out.read_text().splitlines()[0] == "# XMIPP_STAR_1 *"
    pd.testing.assert_frame_equal(
        source["particles"].to_pandas(), again["particles"].to_pandas()
    )
    assert {"_enabled", "_shiftX", "_angleRot2"} <= set(
        again.raw.to_pandas().columns
    )


def test_an_xmd_written_as_star_speaks_relion(tmp_path):
    out = tmp_path / "out.star"

    read("c3_stk.xmd").write(str(out))
    raw = rxm.read(str(out)).raw.to_pandas()

    assert raw["_rlnImageName"][0] == "000001@c3_stk.mrc"
    assert "_rlnAngleRot" in raw.columns
    assert "_enabled" not in raw.columns


def test_a_header_that_is_not_a_comment_is_refused(tmp_path):
    writer = StarWriter(header="data_")
    table = RawTable.of("p", pa.table({"_image": ["1@a.stk"]}))

    with pytest.raises(ValueError, match="not a comment"):
        writer.write_tables(str(tmp_path / "out.xmd"), [table])
