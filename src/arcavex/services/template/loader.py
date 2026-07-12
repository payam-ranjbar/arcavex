"""Template and data loading with source line/column retention.

Authoring YAML is parsed with ``ruamel.yaml`` in round-trip mode so that line and column
locations survive into diagnostics. Object construction is never enabled — only plain
mappings, sequences, and scalars are produced (safe parsing per spec §8.3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import MarkedYAMLError, YAMLError

from arcavex.kernel.diagnostics import DiagnosticError, diagnostic

# Split-template sidecar filenames mapped to the template section they provide. A directory
# template is ``template.yaml`` plus any of these; each sidecar's top-level content IS the
# section value (schema.yaml holds the variables mapping directly, and so on). ``styles.yaml``
# is deliberately absent — style packs are Phase 3 and still rejected.
_SIDECARS: tuple[tuple[str, str], ...] = (
    ("schema.yaml", "variables"),
    ("formats.yaml", "formats"),
    ("locales.yaml", "locales"),
    ("preview-data.yaml", "preview_data"),
    ("preview_data.yaml", "preview_data"),
)


@dataclass(frozen=True)
class TemplateSource:
    """A loaded template: the merged section mapping plus per-section source files.

    ``raw`` is the ``template.yaml`` mapping with any split sidecar sections merged in. Each
    merged section keeps its original ruamel node, so line numbers resolve against the file
    that actually holds it. ``section_files`` records which file each split-able section came
    from so diagnostics point at the right file even for directory templates.
    """

    root_dir: Path
    template_path: Path
    raw: CommentedMap
    section_files: dict[str, Path] = field(default_factory=dict)
    is_split: bool = False

    def file_for(self, section: str) -> Path:
        """Return the file that defines ``section`` (the sidecar, or ``template.yaml``)."""
        return self.section_files.get(section, self.template_path)


def resolve_template_path(path: Path) -> tuple[Path, Path]:
    """Resolve a user-supplied template path to ``(root_dir, template_yaml)``.

    A directory must contain ``template.yaml``; a file is taken as the template document and
    its parent directory is scanned for sidecars (so passing the directory or its
    ``template.yaml`` is equivalent, per spec §4.1.1).

    Raises:
        DiagnosticError: If the path or its ``template.yaml`` does not exist.
    """
    path = Path(path)
    if path.is_dir():
        template_yaml = path / "template.yaml"
        if not template_yaml.is_file():
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-001",
                    f"Directory template has no template.yaml: {path}",
                    file=str(path),
                    hint="A split template directory must contain a 'template.yaml'.",
                )
            )
        return path, template_yaml
    return path.parent, path


def load_template(path: Path) -> TemplateSource:
    """Load a one-file or split template into a merged :class:`TemplateSource`.

    Inline (``template.yaml``) and split (sidecar) definitions of the same section are a
    located ``ARC-TPL-097`` error rather than a precedence puzzle (spec §4.1.1). One-file and
    split forms produce identical merged content.
    """
    root_dir, template_yaml = resolve_template_path(path)
    raw = load_yaml(template_yaml)
    if not isinstance(raw, CommentedMap):
        # Fall back to the compiler's own "root must be a mapping" handling by returning the
        # non-mapping value wrapped; the compiler reports ARC-TPL-003.
        raise DiagnosticError(
            diagnostic(
                "ARC-TPL-003",
                "Template root must be a mapping",
                file=str(template_yaml),
                hint="A template file is a YAML mapping with 'root:' and other sections.",
            )
        )

    section_files: dict[str, Path] = {}
    is_split = False
    seen_sidecar: dict[str, str] = {}
    for filename, section in _SIDECARS:
        sidecar = root_dir / filename
        if not sidecar.is_file():
            continue
        is_split = True
        if section in raw:
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-097",
                    f"Section {section!r} is defined both inline and in {filename!r}",
                    file=str(template_yaml),
                    keypath=section,
                    line=line_of(raw, section),
                    hint=f"Keep {section!r} in one place: either template.yaml or {filename}.",
                )
            )
        if section in seen_sidecar:
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-097",
                    f"Section {section!r} is defined in both {seen_sidecar[section]!r} "
                    f"and {filename!r}",
                    file=str(sidecar),
                    hint=f"Provide {section!r} in exactly one sidecar file.",
                )
            )
        seen_sidecar[section] = filename
        raw[section] = load_yaml(sidecar)
        section_files[section] = sidecar
    return TemplateSource(
        root_dir=root_dir,
        template_path=template_yaml,
        raw=raw,
        section_files=section_files,
        is_split=is_split,
    )


def _yaml() -> YAML:
    parser = YAML(typ="rt")
    parser.preserve_quotes = True
    return parser


def dump_yaml(data: Any, path: Path) -> None:
    """Write ``data`` to ``path`` in round-trip YAML, preserving comments where possible."""
    with path.open("w", encoding="utf-8") as handle:
        _yaml().dump(data, handle)


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
