import rexlib_metadata


def test_import():
    assert rexlib_metadata is not None


def test_version():
    version = rexlib_metadata.__version__
    assert isinstance(version, str)
    assert len(version) > 0
