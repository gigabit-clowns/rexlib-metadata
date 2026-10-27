# SPDX-License-Identifier: LGPL-2.1-or-later

import inspect

import rexlib_metadata


def test_version():
    version = rexlib_metadata.__version__
    assert isinstance(version, str)
    assert len(version) > 0


def test_the_public_signature_resolves_at_runtime():
    signature = inspect.signature(rexlib_metadata.read, eval_str=True)

    assert signature.parameters["bundle"].annotation is not None
