"""The canonical columns, as `docs/canonical.md` describes them."""

from __future__ import annotations

import pyarrow as pa

from rexlib_metadata.schema import (
    ColumnDescriptor,
    Schema,
    SchemaTrait,
    TableSchema,
)

IMAGE_REFERENCE = SchemaTrait(
    "image_reference",
    (
        ColumnDescriptor("image_path", pa.string(), required=True),
        ColumnDescriptor("image_index", pa.int64(), required=True),
    ),
)

MICROGRAPH = SchemaTrait(
    "micrograph",
    (ColumnDescriptor("micrograph_path", pa.string()),),
)

CARTESIAN_POSITION = SchemaTrait(
    "cartesian_position",
    (
        ColumnDescriptor("coord_x", pa.float64(), unit="px"),
        ColumnDescriptor("coord_y", pa.float64(), unit="px"),
        ColumnDescriptor("coord_z", pa.float64(), unit="px"),
    ),
)

EULER_ANGLES = SchemaTrait(
    "euler_angles",
    (
        ColumnDescriptor("angle_rot", pa.float64(), unit="degrees"),
        ColumnDescriptor("angle_tilt", pa.float64(), unit="degrees"),
        ColumnDescriptor("angle_psi", pa.float64(), unit="degrees"),
    ),
)

CTF_QUALITY = SchemaTrait(
    "ctf_quality",
    (ColumnDescriptor("ctf_max_resolution", pa.float64(), unit="A"),),
)

OPTICS_KEY = SchemaTrait(
    "optics_key",
    (ColumnDescriptor("optics_group", pa.int32()),),
)

MICROSCOPE = SchemaTrait(
    "microscope",
    (
        ColumnDescriptor("voltage", pa.float64(), unit="kV"),
        ColumnDescriptor("spherical_aberration", pa.float64(), unit="mm"),
        ColumnDescriptor("amplitude_contrast", pa.float64(), unit="fraction"),
    ),
)

SAMPLING = SchemaTrait(
    "sampling",
    (
        ColumnDescriptor("pixel_size", pa.float64(), unit="A/px"),
        ColumnDescriptor("image_size", pa.int64(), unit="px"),
        ColumnDescriptor("image_dimensionality", pa.int32()),
    ),
)

PARTICLES = TableSchema(
    "particles",
    IMAGE_REFERENCE,
    MICROGRAPH,
    CARTESIAN_POSITION,
    EULER_ANGLES,
    CTF_QUALITY,
    OPTICS_KEY,
)

OPTICS = TableSchema(
    "optics",
    ColumnDescriptor("optics_group", pa.int32(), required=True),
    MICROSCOPE,
    SAMPLING,
)

SCHEMA = Schema(PARTICLES, OPTICS)
