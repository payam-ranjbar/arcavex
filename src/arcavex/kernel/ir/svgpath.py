"""Strict SVG path-data parser producing absolute, normalized path commands.

skia-python 144 exposes no SVG path parser, so a ``path`` node's ``d`` attribute is parsed here
into a small command vocabulary the renderer maps one-to-one onto ``skia.Path``: ``M`` (move),
``L`` (line), ``C`` (cubic), ``Q`` (quadratic), ``A`` (SVG arc), and ``Z`` (close). Every SVG
command is accepted on input — ``M/m L/l H/h V/v C/c S/s Q/q T/t A/a Z/z``, with implicit
repeats, comma or whitespace separators, and exponent numbers — and normalized on the way in:
relative coordinates become absolute, ``H``/``V`` become ``L``, and the smooth ``S``/``T``
forms get their reflected control point made explicit. The grammar is strict: an unknown
command letter, a missing or malformed number, an arc flag other than 0/1, or data that does not
start with a move is an :class:`SvgPathError` naming the offending token and its offset, which
the compiler turns into a located diagnostic. Coordinates stay in the author's unit; the caller
scales them into points with :meth:`PathCommand.scaled`.
"""

from __future__ import annotations

import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

PathOp = Literal["M", "L", "C", "Q", "A", "Z"]

# How many numbers each SVG command consumes per repetition.
_ARG_COUNTS: dict[str, int] = {
    "M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0,
}
# Positions (within an arc's seven arguments) that are 0/1 flags rather than numbers.
_ARC_FLAG_POSITIONS = frozenset({3, 4})
_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
# Whitespace, or a single comma with optional whitespace on either side.
_SEPARATOR = re.compile(r"\s*,?\s*")
_TOKEN = re.compile(r"[^\s,]+")
#: The ``token`` an :class:`SvgPathError` carries when the data ended too early.
END_OF_DATA = "end of data"


class SvgPathError(ValueError):
    """Malformed SVG path data; ``token`` and ``index`` locate the offending text."""

    def __init__(self, message: str, token: str, index: int) -> None:
        super().__init__(f"{message} (at offset {index}, near {token!r})")
        self.reason = message
        self.token = token
        self.index = index


class PathCommand(BaseModel):
    """One absolute, normalized path command.

    ``args`` by ``op``: ``M``/``L`` are ``(x, y)``; ``C`` is ``(x1, y1, x2, y2, x, y)``; ``Q`` is
    ``(x1, y1, x, y)``; ``A`` is ``(rx, ry, x_axis_rotation_deg, large_arc, sweep, x, y)`` with
    the two flags stored as ``0.0``/``1.0``; ``Z`` has none.
    """

    model_config = ConfigDict(frozen=True)

    op: PathOp
    args: tuple[float, ...] = ()

    def scaled(self, factor: float) -> PathCommand:
        """Return this command with every length multiplied by ``factor``.

        An arc's rotation angle and its two flags are not lengths and pass through unchanged.
        """
        if self.op == "A":
            rx, ry, rotation, large_arc, sweep, x, y = self.args
            return PathCommand(
                op="A",
                args=(rx * factor, ry * factor, rotation, large_arc, sweep, x * factor, y * factor),
            )
        return PathCommand(op=self.op, args=tuple(value * factor for value in self.args))


def parse_svg_path(data: str) -> tuple[PathCommand, ...]:
    """Parse SVG path data into absolute, normalized commands.

    Raises:
        SvgPathError: The data is empty, does not start with a move, uses an unknown command
            letter, is missing a number, has an arc flag other than 0 or 1, or contains a
            number too large to represent.
    """
    return _Parser(data).run()


class _Parser:
    def __init__(self, data: str) -> None:
        self._data = data
        self._pos = 0
        self._current = (0.0, 0.0)
        self._subpath_start = (0.0, 0.0)
        # The previous command's last control point, used by S/T when it follows C/S or Q/T.
        self._last_cubic_control: tuple[float, float] | None = None
        self._last_quad_control: tuple[float, float] | None = None
        self._out: list[PathCommand] = []

    # ------------------------------------------------------------------ driver
    def run(self) -> tuple[PathCommand, ...]:
        self._skip_whitespace()
        if self._at_end():
            raise SvgPathError("path data is empty", END_OF_DATA, self._pos)
        first = self._data[self._pos]
        if first not in ("M", "m"):
            raise SvgPathError(
                "path data must start with a move command (M or m)", self._token(), self._pos
            )
        while True:
            self._skip_whitespace()
            if self._at_end():
                break
            letter = self._data[self._pos]
            if letter.upper() not in _ARG_COUNTS:
                raise SvgPathError("unknown path command", self._token(), self._pos)
            self._pos += 1
            self._command(letter)
        return tuple(self._out)

    def _command(self, letter: str) -> None:
        upper = letter.upper()
        relative = letter.islower()
        count = _ARG_COUNTS[upper]
        if count == 0:
            self._close()
            self._skip_separator()
            if not self._at_end() and self._number_ahead():
                raise SvgPathError("'Z' takes no numbers", self._token(), self._pos)
            return
        while True:
            args = self._read_args(letter, count)
            self._emit(upper, relative, args)
            self._skip_separator()
            if self._at_end() or not self._number_ahead():
                return
            # Implicit repeat: further numbers reuse the command; a repeated move draws lines.
            if upper == "M":
                upper = "L"

    # ------------------------------------------------------------------ emitters
    def _emit(self, op: str, relative: bool, args: list[float]) -> None:
        cx, cy = self._current
        if op == "M":
            x, y = args
            # A relative move opening a subpath is relative to the current point (the previous
            # subpath's start after Z); the very first one in the data is absolute by definition.
            if relative and self._out:
                x, y = cx + x, cy + y
            self._current = self._subpath_start = (x, y)
            self._out.append(PathCommand(op="M", args=(x, y)))
            self._reset_controls()
            return
        if op == "L":
            x, y = args
            if relative:
                x, y = cx + x, cy + y
            self._line_to(x, y)
            return
        if op == "H":
            (x,) = args
            self._line_to(cx + x if relative else x, cy)
            return
        if op == "V":
            (y,) = args
            self._line_to(cx, cy + y if relative else y)
            return
        if op == "C":
            x1, y1, x2, y2, x, y = args
            if relative:
                x1, y1, x2, y2, x, y = cx + x1, cy + y1, cx + x2, cy + y2, cx + x, cy + y
            self._cubic_to(x1, y1, x2, y2, x, y)
            return
        if op == "S":
            x2, y2, x, y = args
            if relative:
                x2, y2, x, y = cx + x2, cy + y2, cx + x, cy + y
            x1, y1 = self._reflect(self._last_cubic_control)
            self._cubic_to(x1, y1, x2, y2, x, y)
            return
        if op == "Q":
            x1, y1, x, y = args
            if relative:
                x1, y1, x, y = cx + x1, cy + y1, cx + x, cy + y
            self._quad_to(x1, y1, x, y)
            return
        if op == "T":
            x, y = args
            if relative:
                x, y = cx + x, cy + y
            x1, y1 = self._reflect(self._last_quad_control)
            self._quad_to(x1, y1, x, y)
            return
        # Arc: radii are magnitudes (SVG takes their absolute value); only the end point is
        # affected by the relative form.
        rx, ry, rotation, large_arc, sweep, x, y = args
        if relative:
            x, y = cx + x, cy + y
        self._out.append(
            PathCommand(op="A", args=(abs(rx), abs(ry), rotation, large_arc, sweep, x, y))
        )
        self._current = (x, y)
        self._reset_controls()

    def _line_to(self, x: float, y: float) -> None:
        self._out.append(PathCommand(op="L", args=(x, y)))
        self._current = (x, y)
        self._reset_controls()

    def _cubic_to(self, x1: float, y1: float, x2: float, y2: float, x: float, y: float) -> None:
        self._out.append(PathCommand(op="C", args=(x1, y1, x2, y2, x, y)))
        self._current = (x, y)
        self._last_cubic_control = (x2, y2)
        self._last_quad_control = None

    def _quad_to(self, x1: float, y1: float, x: float, y: float) -> None:
        self._out.append(PathCommand(op="Q", args=(x1, y1, x, y)))
        self._current = (x, y)
        self._last_quad_control = (x1, y1)
        self._last_cubic_control = None

    def _close(self) -> None:
        self._out.append(PathCommand(op="Z"))
        self._current = self._subpath_start
        self._reset_controls()

    def _reflect(self, control: tuple[float, float] | None) -> tuple[float, float]:
        """The previous control point mirrored through the current point, else the point itself."""
        cx, cy = self._current
        if control is None:
            return cx, cy
        return 2.0 * cx - control[0], 2.0 * cy - control[1]

    def _reset_controls(self) -> None:
        self._last_cubic_control = None
        self._last_quad_control = None

    # ------------------------------------------------------------------ lexing
    def _read_args(self, letter: str, count: int) -> list[float]:
        args: list[float] = []
        for position in range(count):
            self._skip_separator()
            if letter.upper() == "A" and position in _ARC_FLAG_POSITIONS:
                args.append(self._read_flag(letter))
            else:
                args.append(self._read_number(letter, count))
        return args

    def _read_number(self, letter: str, count: int) -> float:
        match = _NUMBER.match(self._data, self._pos)
        if match is None:
            plural = "s" if count != 1 else ""
            raise SvgPathError(
                f"command {letter!r} needs {count} number{plural}", self._token(), self._pos
            )
        value = float(match.group(0))
        if not math.isfinite(value):
            raise SvgPathError("number is out of range", match.group(0), self._pos)
        self._pos = match.end()
        return value

    def _read_flag(self, letter: str) -> float:
        if self._at_end() or self._data[self._pos] not in ("0", "1"):
            raise SvgPathError(
                f"arc command {letter!r} flags must be 0 or 1", self._token(), self._pos
            )
        flag = float(self._data[self._pos])
        self._pos += 1
        return flag

    def _number_ahead(self) -> bool:
        return _NUMBER.match(self._data, self._pos) is not None

    def _skip_whitespace(self) -> None:
        while not self._at_end() and self._data[self._pos].isspace():
            self._pos += 1

    def _skip_separator(self) -> None:
        match = _SEPARATOR.match(self._data, self._pos)
        if match is not None:
            self._pos = match.end()

    def _at_end(self) -> bool:
        return self._pos >= len(self._data)

    def _token(self) -> str:
        """The text at the cursor, for an error message (``end of data`` past the last char)."""
        match = _TOKEN.match(self._data, self._pos)
        if match is None:
            return END_OF_DATA
        return match.group(0)
