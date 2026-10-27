# SPDX-License-Identifier: LGPL-2.1-or-later

import rexlib_metadata


def test_version():
    version = rexlib_metadata.__version__
    assert isinstance(version, str)
    assert len(version) > 0
