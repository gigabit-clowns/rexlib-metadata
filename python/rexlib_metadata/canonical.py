# SPDX-License-Identifier: LGPL-2.1-or-later

"""The canonical columns, as `docs/canonical.md` describes them."""

from __future__ import annotations

import pyarrow as pa

from rexlib_metadata.pose import TRANSFORM
from rexlib_metadata.schema import (
    ColumnDescriptor,
    Relation,
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

POSE = SchemaTrait(
    "pose",
    (ColumnDescriptor("transform", TRANSFORM, unit="A"),),
)

CTF_QUALITY = SchemaTrait(
    "ctf_quality",
    (ColumnDescriptor("ctf_max_resolution", pa.float64(), unit="A"),),
)

DEFOCUS = SchemaTrait(
    "defocus",
    (
        ColumnDescriptor("defocus_u", pa.float64(), unit="A"),
        ColumnDescriptor("defocus_v", pa.float64(), unit="A"),
        ColumnDescriptor("defocus_angle", pa.float64(), unit="degrees"),
    ),
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
    POSE,
    CTF_QUALITY,
    OPTICS_KEY,
)

OPTICS = TableSchema(
    "optics",
    ColumnDescriptor("optics_group", pa.int32(), required=True),
    MICROSCOPE,
    SAMPLING,
)

MICROGRAPHS = TableSchema(
    "micrographs",
    ColumnDescriptor("micrograph_path", pa.string(), required=True),
    DEFOCUS,
    CTF_QUALITY,
    OPTICS_KEY,
)

SCHEMA = Schema(
    PARTICLES,
    OPTICS,
    MICROGRAPHS,
    relations=(
        Relation("particles", "optics", "optics_group"),
        Relation("micrographs", "optics", "optics_group"),
    ),
)
