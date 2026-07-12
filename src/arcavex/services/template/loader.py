"""Template and data loading with source line/column retention.

Authoring YAML is parsed with ``ruamel.yaml`` in round-trip mode so that line and column
locations survive into diagnostics. Object construction is never enabled — only plain
mappings, sequences, and scalars are produced (safe parsing per spec §8.3).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import MarkedYAMLError, YAMLError

from arcavex.kernel.diagnostics import DiagnosticError, diagnostic


def _yaml() -> YAML:
    parser = YAML(typ="rt")
    parser.preserve_quotes = True
    return parser


def load_yaml(path: Path) -> Any:
    """Load a YAML file, returning ruamel structures that carry line info.

    Raises:
        DiagnosticError: If the file is missing or not valid YAML.
    """
    if not path.is_file():
        raise DiagnosticError(
            diagnostic(
                "ARC-TPL-001",
                f"File not found: {path}",
                file=str(path),
                hint="Check the path passed on the command line.",
            )
        )
    try:
        text = path.read_text(encoding="utf-8")
        return _yaml().load(text)
    except YAMLError as exc:
        message, line = _yaml_error_summary(exc, path.name)
        raise DiagnosticError(
            diagnostic(
                "ARC-TPL-002",
                message,
                file=str(path),
                line=line,
                hint="Fix the YAML syntax error at the reported location.",
            )
        ) from exc


def _yaml_error_summary(exc: YAMLError, name: str) -> tuple[str, int | None]:
    """Reduce a ruamel error to one clean sentence plus a 1-based line, if known.

    ruamel's ``str(exc)`` repeats the ``in "<unicode string>"`` scaffolding and the mark;
    the structured ``problem``/``problem_mark`` fields give a far cleaner diagnostic.
    """
    if isinstance(exc, MarkedYAMLError) and exc.problem:
        problem = exc.problem.strip()
        mark = exc.problem_mark
        if mark is not None:
            return f"Invalid YAML in {name}: {problem}", int(mark.line) + 1
        return f"Invalid YAML in {name}: {problem}", None
    first_line = str(exc).splitlines()[0] if str(exc) else "syntax error"
    return f"Invalid YAML in {name}: {first_line}", None


def line_of(node: Any, key: str) -> int | None:
    """Return the 1-based line where ``key`` is defined in a mapping, if known."""
    if isinstance(node, CommentedMap):
        try:
            info = node.lc.data.get(key)  # type: ignore[union-attr]
        except AttributeError:
            return None
        if info:
            return int(info[0]) + 1
    return None


def node_line(node: Any) -> int | None:
    """Return the 1-based starting line of a mapping or sequence, if known."""
    if isinstance(node, (CommentedMap, CommentedSeq)):
        lc = node.lc
        if lc.line is not None:
            return int(lc.line) + 1
    return None
