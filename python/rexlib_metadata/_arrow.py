"""The boundary with the compiled module, where Arrow crosses over."""

from __future__ import annotations

import pyarrow as pa


def to_pyarrow_table(obj: object) -> pa.Table:
    """Return what a Rust entry point handed back as a pyarrow table."""
    return pa.Table.from_batches([pa.record_batch(obj)])
