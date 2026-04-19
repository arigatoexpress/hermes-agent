"""File parsers -- convert binary formats (.pdf, .docx, .pptx) to markdown.

FileParser ABC defines the contract. Built-in backends: markitdown, pandoc.
CompositeParser routes extensions to the configured backend.
"""

from __future__ import annotations

import logging
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from workspace.config import ParsingConfig
from workspace.constants import PARSEABLE_SUFFIXES

log = logging.getLogger(__name__)


class FileParser(ABC):
    name: ClassVar[str]

    @abstractmethod
    def supported_suffixes(self) -> frozenset[str]: ...

    @abstractmethod
    def _convert(self, path: Path) -> str: ...

    def parse(self, path: Path) -> str | None:
        try:
            result = self._convert(path)
            return result if result and result.strip() else None
        except Exception as exc:
            log.warning("Parser %s failed on %s: %s", self.name, path, exc)
            return None


class MarkitdownParser(FileParser):
    name = "markitdown"

    def supported_suffixes(self) -> frozenset[str]:
        return frozenset({".pdf", ".docx", ".pptx"})

    def _convert(self, path: Path) -> str:
        from markitdown import MarkItDown

        md = MarkItDown()
        result = md.convert(str(path))
        return result.markdown


class PandocParser(FileParser):
    name = "pandoc"

    def supported_suffixes(self) -> frozenset[str]:
        return frozenset({".pdf", ".docx", ".pptx"})

    def _convert(self, path: Path) -> str:
        result = subprocess.run(
            ["pandoc", str(path), "-t", "markdown"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        result.check_returncode()
        return result.stdout


class CompositeParser:
    """Routes file extensions to the appropriate parser backend."""

    def __init__(self, routing: dict[str, FileParser]) -> None:
        self._routing = routing

    def parse(self, path: Path) -> str | None:
        suffix = path.suffix.lower()
        parser = self._routing.get(suffix)
        if parser is None:
            return None
        return parser.parse(path)

    def can_parse(self, suffix: str) -> bool:
        return suffix in self._routing


_PARSER_CLASSES: list[type[FileParser]] = [MarkitdownParser, PandocParser]


def build_parser(config: ParsingConfig) -> CompositeParser:
    available: dict[str, FileParser] = {}
    for cls in _PARSER_CLASSES:
        instance = cls()
        available[instance.name] = instance

    routing: dict[str, FileParser] = {}
    for suffix in PARSEABLE_SUFFIXES:
        backend_name = config.overrides.get(suffix, config.default)
        parser = available.get(backend_name)
        if parser is not None and suffix in parser.supported_suffixes():
            routing[suffix] = parser

    return CompositeParser(routing)
