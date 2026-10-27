# SPDX-License-Identifier: LGPL-2.1-or-later

import pytest

from rexlib_metadata.convention import (
    ConventionBundle,
    RawSchema,
    ReadConvention,
    WriteConvention,
)


class EulerAngles(ReadConvention):
    source_columns = ("_rlnAngleRot", "_rlnAngleTilt", "_rlnAnglePsi")
    target_columns = ("angle_rot", "angle_tilt", "angle_psi")

    def matches(self, raw):
        return raw.has(*self.source_columns)

    def load(self, table):
        return {
            canonical: table.column(source)
            for source, canonical in zip(self.source_columns,
                                         self.target_columns, strict=True)
        }


class Defocus(ReadConvention):
    source_columns = ("_rlnDefocusU", "_rlnDefocusV")
    target_columns = ("defocus_u", "defocus_v")

    def matches(self, raw):
        return raw.has(*self.source_columns)

    def load(self, table):
        return {}


class OtherEulerAngles(EulerAngles):
    source_columns = ("myAngle1", "myAngle2", "myAngle3")


class WriteEulerAngles(WriteConvention):
    source_columns = ("angle_rot", "angle_tilt", "angle_psi")
    target_columns = ("_rlnAngleRot", "_rlnAngleTilt", "_rlnAnglePsi")

    def store(self, canonical):
        return {}


class Silent(ReadConvention):
    source_columns = ("_rlnAngleRot",)

    def matches(self, raw):
        return True

    def load(self, table):
        return {}


PARTICLES = RawSchema(
    "particles",
    ("_rlnAngleRot", "_rlnAngleTilt", "_rlnAnglePsi", "_rlnDefocusU"),
)


def test_a_raw_schema_answers_for_the_columns_it_has():
    assert PARTICLES.has("_rlnAngleRot", "_rlnDefocusU")
    assert not PARTICLES.has("_rlnAngleRot", "_rlnPhaseShift")


def test_a_convention_matches_on_the_columns_it_consumes():
    assert EulerAngles().matches(PARTICLES)
    assert not Defocus().matches(PARTICLES)


def test_a_bundle_holds_its_conventions_both_ways():
    bundle = ConventionBundle(
        "relion4",
        {"particles": [EulerAngles()]},
        {"particles": [WriteEulerAngles()]},
    )

    assert bundle.name == "relion4"
    assert bundle.tables == ("particles",)
    assert len(bundle.read_conventions("particles")) == 1
    assert len(bundle.write_conventions("particles")) == 1


def test_an_empty_bundle_is_allowed():
    bundle = ConventionBundle("empty")

    assert bundle.tables == ()
    assert bundle.read_conventions("particles") == ()


def test_a_bundle_offers_a_table_nothing_of_another():
    bundle = ConventionBundle(
        "relion4",
        {"particles": [EulerAngles()], "optics": [Defocus()]},
    )

    assert bundle.read_conventions("particles") == bundle._read["particles"]
    assert bundle.read_conventions("nothing_like_it") == ()


def test_one_column_from_two_tables_is_not_a_collision():
    ConventionBundle(
        "relion4",
        {"particles": [EulerAngles()], "optics": [OtherEulerAngles()]},
    )


def test_two_readers_of_one_canonical_column_are_an_error():
    conventions = [EulerAngles(), OtherEulerAngles()]

    with pytest.raises(ValueError, match="angle_rot"):
        ConventionBundle("relion4", {"particles": conventions})


def test_two_writers_of_one_file_column_are_an_error():
    conventions = [WriteEulerAngles(), WriteEulerAngles()]

    with pytest.raises(ValueError, match="_rlnAngleRot"):
        ConventionBundle("relion4", write={"particles": conventions})


def test_the_two_sides_do_not_collide_with_each_other():
    bundle = ConventionBundle(
        "relion4",
        {"particles": [EulerAngles()]},
        {"particles": [WriteEulerAngles()]},
    )
    assert bundle.read_conventions("particles")[0].target_columns == (
        "angle_rot",
        "angle_tilt",
        "angle_psi",
    )


def test_a_convention_that_produces_nothing_is_an_error():
    conventions = [Silent()]

    with pytest.raises(ValueError, match="no target_columns"):
        ConventionBundle("relion4", {"particles": conventions})
