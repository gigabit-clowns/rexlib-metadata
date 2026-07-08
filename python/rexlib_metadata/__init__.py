from rexlib_metadata._rexlib import version as _version
from rexlib_metadata.registry import global_registry
from rexlib_metadata.result import ReadResult

__version__: str = _version()


def read(path: str, **kwargs) -> ReadResult:
    return global_registry.read(path, **kwargs)


__all__ = ["__version__", "read", "ReadResult"]
