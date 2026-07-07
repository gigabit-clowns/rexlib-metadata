from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pyarrow as pa

    from rexlib_metadata.result import ReadResult


class Reader(ABC):
    @abstractmethod
    def read_all(self, path: str) -> pa.Table: ...

    @abstractmethod
    def read(self, path: str, **kwargs) -> ReadResult: ...


class Convention(ABC):
    @abstractmethod
    def matches(self, raw_schema: tuple[str, list[str]]) -> bool: ...

    @abstractmethod
    def apply(self, batch): ...

    @abstractmethod
    def to_file_name(self, canonical_name: str) -> str: ...

    @abstractmethod
    def to_canonical_name(self, file_name: str) -> str: ...
