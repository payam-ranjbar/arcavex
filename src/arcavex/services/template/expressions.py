"""Expression evaluator v0 — a constrained, deterministic ``{{ … }}`` language.

Hand-rolled tokenizer, recursive-descent parser, and tree-walking evaluator (no ``eval``).
Explicitly not Turing-complete: no I/O, no imports, no host attribute access, no recursion,
no unbounded loops. Supports literals, dotted/indexed variable paths, arithmetic,
comparisons, boolean ``and``/``or``/``not``, ternary ``a if cond else b``, string concat,
the functions ``len``/``upper``/``lower``/``format``, and the ``x | default(v)`` operator.

A per-expression evaluation-step cap and a 10 ms wall budget guard against pathological
input; neither is an input to the rendered output, so determinism is preserved.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Union

from arcavex.services.template.functions import BUILTIN_FUNCTIONS

# Union (not ``|``) because the recursive forward reference is not evaluable at runtime.
Value = Union[str, int, float, bool, None, list["Value"], dict[str, "Value"]]  # noqa: UP007

# A function table resolves a call name plus evaluated arguments to a value. It raises
# :class:`UnknownFunctionError` for an unregistered name and :class:`ValueError` for a bad
# call; the evaluator wraps the latter as an expression error. Production wires a
# registry-backed table (``arcavex.bootstrap``); standalone use falls back to the built-ins.
FunctionTable = Callable[[str, list["Value"]], "Value"]

_STEP_CAP = 100_000
_TIME_BUDGET_S = 0.010
# Reject pathologically large expressions before building/walking a deep AST. The v0
# language has no loops, so token count bounds both parse depth and evaluation cost.
_TOKEN_CAP = 4_000


class ExpressionError(Exception):
    """A syntax or evaluation error in a template expression."""

    def __init__(self, message: str, *, pos: int | None = None) -> None:
        self.message = message
        self.pos = pos
        super().__init__(message)


class MissingVariableError(ExpressionError):
    """A referenced variable or path segment does not exist."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"variable '{path}' is not defined")


class BudgetError(ExpressionError):
    """The expression exceeded its evaluation budget."""


class UnknownFunctionError(ExpressionError):
    """A call references a function name that is not registered."""

    def __init__(self, name: str, available: list[str]) -> None:
        self.func_name = name
        self.available = available
        detail = f" (available: {', '.join(available)})" if available else ""
        super().__init__(f"unknown function {name!r}{detail}")


def default_function_table() -> FunctionTable:
    """Return a table backed by the built-in functions, for standalone evaluation."""

    def table(name: str, args: list[Value]) -> Value:
        fn = BUILTIN_FUNCTIONS.get(name)
        if fn is None:
            raise UnknownFunctionError(name, sorted(BUILTIN_FUNCTIONS))
        return fn(args)

    return table


# --------------------------------------------------------------------------- tokenizer
@dataclass(frozen=True)
class _Token:
    kind: str
    value: str
    pos: int


_KEYWORDS = {"if", "else", "and", "or", "not", "is", "true", "false", "none", "null"}
_TWO_CHAR_OPS = {"==", "!=", "<=", ">="}
_ONE_CHAR_OPS = set("+-*/%<>|")


def _tokenize(src: str) -> list[_Token]:
    tokens: list[_Token] = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch.isspace():
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            j = i + 1
            buf: list[str] = []
            while j < n and src[j] != quote:
                if src[j] == "\\" and j + 1 < n:
                    nxt = src[j + 1]
                    buf.append({"n": "\n", "t": "\t", "\\": "\\", quote: quote}.get(nxt, nxt))
                    j += 2
                    continue
                buf.append(src[j])
                j += 1
            if j >= n:
                raise ExpressionError("unterminated string literal", pos=i)
            tokens.append(_Token("STRING", "".join(buf), i))
            i = j + 1
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and src[i + 1].isdigit()):
            j = i
            seen_dot = False
            while j < n and (src[j].isdigit() or (src[j] == "." and not seen_dot)):
                if src[j] == ".":
                    seen_dot = True
                j += 1
            tokens.append(_Token("NUMBER", src[i:j], i))
            i = j
            continue
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            word = src[i:j]
            kind = "KEYWORD" if word in _KEYWORDS else "NAME"
            tokens.append(_Token(kind, word, i))
            i = j
            continue
        two = src[i : i + 2]
        if two in _TWO_CHAR_OPS:
            tokens.append(_Token("OP", two, i))
            i += 2
            continue
        if ch in _ONE_CHAR_OPS:
            tokens.append(_Token("OP", ch, i))
            i += 1
            continue
        if ch in "()[].,":
            tokens.append(_Token("PUNCT", ch, i))
            i += 1
            continue
        raise ExpressionError(f"unexpected character {ch!r}", pos=i)
    tokens.append(_Token("EOF", "", n))
    return tokens


# ------------------------------------------------------------------------------- AST
@dataclass(frozen=True)
class _Node:
    pass


@dataclass(frozen=True)
class _Lit(_Node):
    value: Value


@dataclass(frozen=True)
class _Var(_Node):
    name: str


@dataclass(frozen=True)
class _Attr(_Node):
    target: _Node
    name: str


@dataclass(frozen=True)
class _Index(_Node):
    target: _Node
    index: _Node


@dataclass(frozen=True)
class _Unary(_Node):
    op: str
    operand: _Node


@dataclass(frozen=True)
class _Binary(_Node):
    op: str
    left: _Node
    right: _Node


@dataclass(frozen=True)
class _Is(_Node):
    left: _Node
    right: _Node
    negate: bool


@dataclass(frozen=True)
class _Ternary(_Node):
    cond: _Node
    if_true: _Node
    if_false: _Node


@dataclass(frozen=True)
class _Call(_Node):
    func: str
    args: tuple[_Node, ...]


@dataclass(frozen=True)
class _Filter(_Node):
    target: _Node
    name: str
    args: tuple[_Node, ...]


# ---------------------------------------------------------------------------- parser
class _Parser:
    def __init__(self, tokens: list[_Token]) -> None:
        self._tokens = tokens
        self._i = 0

    def _peek(self) -> _Token:
        return self._tokens[self._i]

    def _advance(self) -> _Token:
        tok = self._tokens[self._i]
        self._i += 1
        return tok

    def _expect(self, kind: str, value: str | None = None) -> _Token:
        tok = self._peek()
        if tok.kind != kind or (value is not None and tok.value != value):
            want = value if value is not None else kind
            found = tok.value or tok.kind
            raise ExpressionError(f"expected {want!r}, found {found!r}", pos=tok.pos)
        return self._advance()

    def parse(self) -> _Node:
        node = self._ternary()
        if self._peek().kind != "EOF":
            tok = self._peek()
            raise ExpressionError(f"unexpected token {tok.value or tok.kind!r}", pos=tok.pos)
        return node

    def _ternary(self) -> _Node:
        expr = self._pipe()
        tok = self._peek()
        if tok.kind == "KEYWORD" and tok.value == "if":
            self._advance()
            cond = self._pipe()
            self._expect("KEYWORD", "else")
            if_false = self._ternary()
            return _Ternary(cond, expr, if_false)
        return expr

    def _pipe(self) -> _Node:
        left = self._or()
        while self._peek().kind == "OP" and self._peek().value == "|":
            self._advance()
            name_tok = self._expect("NAME")
            args: tuple[_Node, ...] = ()
            if self._peek().kind == "PUNCT" and self._peek().value == "(":
                args = self._arg_list()
            left = _Filter(left, name_tok.value, args)
        return left

    def _or(self) -> _Node:
        left = self._and()
        while self._peek().kind == "KEYWORD" and self._peek().value == "or":
            self._advance()
            left = _Binary("or", left, self._and())
        return left

    def _and(self) -> _Node:
        left = self._not()
        while self._peek().kind == "KEYWORD" and self._peek().value == "and":
            self._advance()
            left = _Binary("and", left, self._not())
        return left

    def _not(self) -> _Node:
        tok = self._peek()
        if tok.kind == "KEYWORD" and tok.value == "not":
            self._advance()
            return _Unary("not", self._not())
        return self._comparison()

    def _comparison(self) -> _Node:
        left = self._additive()
        # 'is' / 'is not' identity test (chiefly 'x is none' / 'x is not none'); it does not
        # chain, so it is handled before the relational operators.
        if self._peek().kind == "KEYWORD" and self._peek().value == "is":
            self._advance()
            negate = False
            if self._peek().kind == "KEYWORD" and self._peek().value == "not":
                self._advance()
                negate = True
            return _Is(left, self._additive(), negate)
        comparisons = {"==", "!=", "<", "<=", ">", ">="}
        while self._peek().kind == "OP" and self._peek().value in comparisons:
            op = self._advance().value
            left = _Binary(op, left, self._additive())
        return left

    def _additive(self) -> _Node:
        left = self._multiplicative()
        while self._peek().kind == "OP" and self._peek().value in {"+", "-"}:
            op = self._advance().value
            left = _Binary(op, left, self._multiplicative())
        return left

    def _multiplicative(self) -> _Node:
        left = self._unary()
        while self._peek().kind == "OP" and self._peek().value in {"*", "/", "%"}:
            op = self._advance().value
            left = _Binary(op, left, self._unary())
        return left

    def _unary(self) -> _Node:
        tok = self._peek()
        if tok.kind == "OP" and tok.value in {"-", "+"}:
            self._advance()
            return _Unary(tok.value, self._unary())
        return self._postfix()

    def _postfix(self) -> _Node:
        node = self._primary()
        while True:
            tok = self._peek()
            if tok.kind == "PUNCT" and tok.value == ".":
                self._advance()
                name = self._expect("NAME")
                node = _Attr(node, name.value)
            elif tok.kind == "PUNCT" and tok.value == "[":
                self._advance()
                index = self._ternary()
                self._expect("PUNCT", "]")
                node = _Index(node, index)
            else:
                break
        return node

    def _primary(self) -> _Node:
        tok = self._peek()
        if tok.kind == "NUMBER":
            self._advance()
            text = tok.value
            return _Lit(float(text) if "." in text else int(text))
        if tok.kind == "STRING":
            self._advance()
            return _Lit(tok.value)
        if tok.kind == "KEYWORD" and tok.value in {"true", "false"}:
            self._advance()
            return _Lit(tok.value == "true")
        if tok.kind == "KEYWORD" and tok.value in {"none", "null"}:
            self._advance()
            return _Lit(None)
        if tok.kind == "NAME":
            self._advance()
            if self._peek().kind == "PUNCT" and self._peek().value == "(":
                args = self._arg_list()
                return _Call(tok.value, args)
            return _Var(tok.value)
        if tok.kind == "PUNCT" and tok.value == "(":
            self._advance()
            node = self._ternary()
            self._expect("PUNCT", ")")
            return node
        raise ExpressionError(f"unexpected token {tok.value or tok.kind!r}", pos=tok.pos)

    def _arg_list(self) -> tuple[_Node, ...]:
        self._expect("PUNCT", "(")
        args: list[_Node] = []
        if not (self._peek().kind == "PUNCT" and self._peek().value == ")"):
            args.append(self._ternary())
            while self._peek().kind == "PUNCT" and self._peek().value == ",":
                self._advance()
                args.append(self._ternary())
        self._expect("PUNCT", ")")
        return tuple(args)


# ------------------------------------------------------------------------- evaluator
class _Evaluator:
    def __init__(self, context: dict[str, Value], functions: FunctionTable) -> None:
        self._ctx = context
        self._functions = functions
        self._steps = 0
        self._deadline = time.perf_counter() + _TIME_BUDGET_S

    def eval(self, node: _Node) -> Value:
        self._steps += 1
        if self._steps > _STEP_CAP:
            raise BudgetError("expression exceeded evaluation step budget")
        if self._steps % 1024 == 0 and time.perf_counter() > self._deadline:
            raise BudgetError("expression exceeded 10ms evaluation budget")

        if isinstance(node, _Lit):
            return node.value
        if isinstance(node, _Var):
            if node.name not in self._ctx:
                raise MissingVariableError(node.name)
            return self._ctx[node.name]
        if isinstance(node, _Attr):
            return self._eval_attr(node)
        if isinstance(node, _Index):
            return self._eval_index(node)
        if isinstance(node, _Unary):
            return self._eval_unary(node)
        if isinstance(node, _Binary):
            return self._eval_binary(node)
        if isinstance(node, _Is):
            return self._eval_is(node)
        if isinstance(node, _Ternary):
            branch = node.if_true if _truthy(self.eval(node.cond)) else node.if_false
            return self.eval(branch)
        if isinstance(node, _Call):
            return self._eval_call(node)
        if isinstance(node, _Filter):
            return self._eval_filter(node)
        raise ExpressionError("unknown expression node")

    def _path_of(self, node: _Node) -> str:
        if isinstance(node, _Var):
            return node.name
        if isinstance(node, _Attr):
            return f"{self._path_of(node.target)}.{node.name}"
        if isinstance(node, _Index):
            return f"{self._path_of(node.target)}[…]"
        return "?"

    def _eval_attr(self, node: _Attr) -> Value:
        target = self.eval(node.target)
        if isinstance(target, dict) and node.name in target:
            return target[node.name]
        raise MissingVariableError(self._path_of(node))

    def _eval_index(self, node: _Index) -> Value:
        target = self.eval(node.target)
        index = self.eval(node.index)
        if isinstance(target, list) and isinstance(index, int) and not isinstance(index, bool):
            if -len(target) <= index < len(target):
                return target[index]
            raise MissingVariableError(f"{self._path_of(node.target)}[{index}]")
        if isinstance(target, dict) and isinstance(index, str):
            if index in target:
                return target[index]
            raise MissingVariableError(f"{self._path_of(node.target)}[{index!r}]")
        raise ExpressionError("invalid index operation")

    def _eval_unary(self, node: _Unary) -> Value:
        if node.op == "not":
            return not _truthy(self.eval(node.operand))
        operand = self.eval(node.operand)
        if not isinstance(operand, (int, float)) or isinstance(operand, bool):
            raise ExpressionError("unary +/- requires a number")
        return -operand if node.op == "-" else +operand

    def _eval_binary(self, node: _Binary) -> Value:
        if node.op == "and":
            left = self.eval(node.left)
            return self.eval(node.right) if _truthy(left) else left
        if node.op == "or":
            left = self.eval(node.left)
            return left if _truthy(left) else self.eval(node.right)
        left = self.eval(node.left)
        right = self.eval(node.right)
        if node.op in {"==", "!="}:
            equal = left == right and type(left) is type(right)
            # allow numeric cross-type equality (1 == 1.0)
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                equal = float(left) == float(right)
            return equal if node.op == "==" else not equal
        if node.op in {"<", "<=", ">", ">="}:
            return _compare(node.op, left, right)
        return _arith(node.op, left, right)

    def _eval_is(self, node: _Is) -> Value:
        left = self.eval(node.left)
        right = self.eval(node.right)
        if left is None or right is None:
            same = left is None and right is None
        else:
            same = left == right and type(left) is type(right)
        return (not same) if node.negate else same

    def _call(self, name: str, args: list[Value]) -> Value:
        try:
            return self._functions(name, args)
        except ValueError as exc:
            # A bad call (wrong arity/type) is an authoring error, surfaced as ARC-TPL-060.
            raise ExpressionError(str(exc)) from exc

    def _eval_call(self, node: _Call) -> Value:
        args = [self.eval(a) for a in node.args]
        return self._call(node.func, args)

    def _eval_filter(self, node: _Filter) -> Value:
        if node.name == "default":
            if len(node.args) != 1:
                raise ExpressionError("default() takes exactly one argument")
            try:
                value = self.eval(node.target)
            except MissingVariableError:
                return self.eval(node.args[0])
            return self.eval(node.args[0]) if value is None else value
        target = self.eval(node.target)
        args = [self.eval(a) for a in node.args]
        return self._call(node.name, [target, *args])


# --------------------------------------------------------------------- helper builtins
def _truthy(value: Value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return len(value) > 0
    if isinstance(value, (list, dict)):
        return len(value) > 0
    raise ExpressionError("value has no defined truthiness")


def _arith(op: str, left: Value, right: Value) -> Value:
    if op == "+" and isinstance(left, str) and isinstance(right, str):
        return left + right
    if not isinstance(left, (int, float)) or isinstance(left, bool):
        raise ExpressionError(f"operator {op!r} requires numbers")
    if not isinstance(right, (int, float)) or isinstance(right, bool):
        raise ExpressionError(f"operator {op!r} requires numbers")
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op in {"/", "%"} and right == 0:
        raise ExpressionError("division by zero")
    if op == "/":
        result = left / right
        return result
    return left % right


def _compare(op: str, left: Value, right: Value) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        lo, ro = float(left), float(right)
    elif isinstance(left, str) and isinstance(right, str):
        lo, ro = left, right  # type: ignore[assignment]
    else:
        raise ExpressionError("comparison requires two numbers or two strings")
    if op == "<":
        return lo < ro
    if op == "<=":
        return lo <= ro
    if op == ">":
        return lo > ro
    return lo >= ro


def stringify(value: Value) -> str:
    """Convert an expression value to its interpolation string form."""
    return _stringify(value)


def _stringify(value: Value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return repr(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value
    raise ExpressionError("cannot interpolate a list or object into a string")


# ------------------------------------------------------------------------- public API
def evaluate_expression(
    src: str, context: dict[str, Value], functions: FunctionTable | None = None
) -> Value:
    """Parse and evaluate a single expression body (without ``{{ }}``).

    Args:
        src: The expression body.
        context: Variable bindings visible to the expression.
        functions: The function-resolution table. Defaults to the built-in functions so
            standalone callers work without wiring a registry; production injects a
            registry-backed table.
    """
    table = functions if functions is not None else default_function_table()
    tokens = _tokenize(src)
    if len(tokens) > _TOKEN_CAP:
        raise BudgetError("expression exceeds the maximum token budget")
    ast = _Parser(tokens).parse()
    return _Evaluator(context, table).eval(ast)


def render_value(
    raw: str, context: dict[str, Value], functions: FunctionTable | None = None
) -> Value:
    """Resolve a scalar string that may contain ``{{ … }}`` expressions.

    If the string is exactly one expression, the native value type is preserved. Otherwise
    each embedded expression is evaluated and stringified into the surrounding text.
    ``\\{{`` is an escaped literal ``{{``.
    """
    if "{{" not in raw and "\\{{" not in raw:
        return raw

    table = functions if functions is not None else default_function_table()
    exact = _match_exact(raw)
    if exact is not None:
        return evaluate_expression(exact, context, table)

    out: list[str] = []
    i = 0
    n = len(raw)
    while i < n:
        if raw[i] == "\\" and raw[i : i + 3] == "\\{{":
            out.append("{{")
            i += 3
            continue
        if raw[i : i + 2] == "{{":
            end = raw.find("}}", i + 2)
            if end == -1:
                raise ExpressionError("unterminated '{{' expression")
            body = raw[i + 2 : end]
            out.append(_stringify(evaluate_expression(body, context, table)))
            i = end + 2
            continue
        out.append(raw[i])
        i += 1
    return "".join(out)


def _match_exact(raw: str) -> str | None:
    stripped = raw.strip()
    if not (stripped.startswith("{{") and stripped.endswith("}}")):
        return None
    inner = stripped[2:-2]
    # Ensure there is exactly one expression (no nested closer before the end).
    if "}}" in inner or "{{" in inner:
        return None
    return inner
