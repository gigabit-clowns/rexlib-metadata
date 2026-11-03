# SPDX-License-Identifier: LGPL-2.1-or-later

import numpy as np
import pandas as pd

from rexlib_metadata import pose


def assert_same(left, right):
    """Compare canonical frames, a transform to its single precision."""
    exact = [c for c in left.columns if c != "transform"]
    pd.testing.assert_frame_equal(left[exact], right[exact])
    if "transform" in left.columns:
        np.testing.assert_allclose(
            pose.matrices(left["transform"]),
            pose.matrices(right["transform"]),
            atol=1e-5,
        )
