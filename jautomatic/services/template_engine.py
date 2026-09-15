"""A deliberately tiny template language for user-supplied CV templates.

Users drop ``*.md`` files into ``<data dir>/templates`` and the app renders
them with their profile.  The syntax is a strict subset of what Jinja users
already know, implemented here so the app keeps its "no extra dependencies,
nothing executes user code" stance:

* ``{{ name }}`` / ``{{ job.title }}`` / ``{{ entry.bullets.0 }}`` – dotted
  lookups; anything missing renders as an empty string (never an error).
* ``{% for entry in experience %} … {% endfor %}`` – loops (nestable); the
  loop variable is scoped to the body.
* ``{% if job %} … {% else %} … {% endif %}`` – truthiness test on a lookup,
  with an optional ``not``: ``{% if not job %}``.
* ``{# a comment #}`` – dropped from the output.

There are no filters, expressions, attribute calls or includes: a template
can only read the values it is given.  Structural mistakes (an ``endfor``
without a ``for``, an unclosed block) raise :class:`TemplateError` with the
line number so the user can fix the file.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_TOKEN = re.compile(r"({{.*?}}|{%.*?%}|{#.*?#})", re.DOTALL)


class TemplateError(ValueError):
    """Malformed template (unbalanced blocks, unknown tag, bad syntax)."""


# --------------------------------------------------------------------------- #
# AST
# --------------------------------------------------------------------------- #
@dataclass
class _Text:
    text: str


@dataclass
class _Var:
    path: str


@dataclass
class _For:
    var: str
    iterable: str
    body: list = field(default_factory=list)


@dataclass
class _If:
    path: str
    negate: bool = False
    body: list = field(default_factory=list)
    orelse: list = field(default_factory=list)


_FOR_RE = re.compile(r"^for\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\s+([A-Za-z_][A-Za-z0-9_.]*)$")
_IF_RE = re.compile(r"^if\s+(not\s+)?([A-Za-z_][A-Za-z0-9_.]*)$")
_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


def _line_of(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def _owns_line(source: str, match: re.Match) -> str | None:
    """If a tag sits on a line of its own, return the indentation before it.

    Block and comment tags that occupy a whole line should vanish from the
    output together with their line break (Jinja's ``trim_blocks`` +
    ``lstrip_blocks``), otherwise ``{% for %}``/``{% endfor %}`` lines leave a
    blank line between every bullet.  ``None`` means "inline tag, keep as is".
    """
    line_start = source.rfind("\n", 0, match.start()) + 1
    prefix = source[line_start:match.start()]
    if prefix.strip() or not source.startswith("\n", match.end()):
        return None
    return prefix


def parse(source: str) -> list:
    """Compile ``source`` into a node list (raises :class:`TemplateError`)."""
    root: list = []
    # stack of (node-being-filled, target list currently appended to, tag, line)
    stack: list[tuple[object, list, str, int]] = []
    current = root
    pos = 0
    for match in _TOKEN.finditer(source):
        token = match.group(0)
        text_end = match.start()
        indent = None if token.startswith("{{") else _owns_line(source, match)
        if indent is not None:
            text_end -= len(indent)          # drop the indentation before the tag
        if text_end > pos:
            current.append(_Text(source[pos:text_end]))
        pos = match.end() + (1 if indent is not None else 0)   # ...and its newline
        line = _line_of(source, match.start())
        if token.startswith("{#"):
            continue
        inner = token[2:-2].strip()
        if token.startswith("{{"):
            if not _VAR_RE.match(inner):
                raise TemplateError(f"line {line}: bad placeholder {{{{ {inner} }}}} — "
                                    "only names like name, job.title or entry.bullets are allowed")
            current.append(_Var(inner))
            continue
        # block tag
        if inner.startswith("for "):
            found = _FOR_RE.match(inner)
            if not found:
                raise TemplateError(f"line {line}: bad loop “{inner}” — "
                                    "expected {% for item in list %}")
            node = _For(var=found.group(1), iterable=found.group(2))
            current.append(node)
            stack.append((node, current, "for", line))
            current = node.body
        elif inner.startswith("if ") or inner == "if":
            found = _IF_RE.match(inner)
            if not found:
                raise TemplateError(f"line {line}: bad condition “{inner}” — "
                                    "expected {% if value %} or {% if not value %}")
            node = _If(path=found.group(2), negate=bool(found.group(1)))
            current.append(node)
            stack.append((node, current, "if", line))
            current = node.body
        elif inner == "else":
            if not stack or stack[-1][2] != "if":
                raise TemplateError(f"line {line}: {{% else %}} outside of an {{% if %}} block")
            node = stack[-1][0]
            if current is node.orelse:  # type: ignore[union-attr]
                raise TemplateError(f"line {line}: second {{% else %}} in the same {{% if %}}")
            current = node.orelse  # type: ignore[union-attr]
        elif inner in ("endfor", "endif"):
            wanted = inner[3:]
            if not stack:
                raise TemplateError(f"line {line}: {{% {inner} %}} without a matching "
                                    f"{{% {wanted} %}}")
            _node, parent, tag, opened = stack.pop()
            if tag != wanted:
                raise TemplateError(f"line {line}: {{% {inner} %}} closes a {{% {tag} %}} "
                                    f"opened on line {opened}")
            current = parent
        else:
            raise TemplateError(f"line {line}: unknown tag {{% {inner} %}} — "
                                "supported: for/endfor, if/else/endif")
    if pos < len(source):
        current.append(_Text(source[pos:]))
    if stack:
        _node, _parent, tag, opened = stack[-1]
        raise TemplateError(f"line {opened}: {{% {tag} %}} is never closed "
                            f"(missing {{% end{tag} %}})")
    return root


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def lookup(context: dict, path: str) -> object:
    """Resolve ``a.b.c`` against dicts, objects and sequences; ``None`` if absent."""
    value: object = context
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, (list, tuple)) and part.isdigit():
            index = int(part)
            value = value[index] if index < len(value) else None
        else:
            if part.startswith("_"):
                return None  # never expose private attributes
            value = getattr(value, part, None)
            if callable(value):
                return None  # and never call anything
        if value is None:
            return None
    return value


def _to_text(value: object) -> str:
    if value is None or value is False:
        return ""
    if value is True:
        return "yes"
    if isinstance(value, (list, tuple)):
        return ", ".join(_to_text(v) for v in value if v not in (None, ""))
    return str(value)


def _render_nodes(nodes: list, context: dict, out: list[str]) -> None:
    for node in nodes:
        if isinstance(node, _Text):
            out.append(node.text)
        elif isinstance(node, _Var):
            out.append(_to_text(lookup(context, node.path)))
        elif isinstance(node, _If):
            truthy = bool(lookup(context, node.path))
            branch = node.body if (truthy != node.negate) else node.orelse
            _render_nodes(branch, context, out)
        elif isinstance(node, _For):
            items = lookup(context, node.iterable)
            if isinstance(items, dict):
                items = list(items.items())
            if not isinstance(items, (list, tuple)):
                items = [] if not items else [items]
            for index, item in enumerate(items):
                scoped = dict(context)
                scoped[node.var] = item
                scoped["loop"] = {"index": index + 1, "index0": index,
                                  "first": index == 0, "last": index == len(items) - 1,
                                  "length": len(items)}
                _render_nodes(node.body, scoped, out)


def render(source: str, context: dict) -> str:
    """Render ``source`` with ``context``; collapses runs of 3+ blank lines."""
    out: list[str] = []
    _render_nodes(parse(source), context, out)
    text = "".join(out)
    text = re.sub(r"[ \t]+\n", "\n", text)          # trailing spaces left by tags
    text = re.sub(r"\n{3,}", "\n\n", text)           # loops/ifs leave gaps behind
    return text.strip() + "\n"


def validate(source: str) -> str | None:
    """Return an error message for a broken template, ``None`` when it parses."""
    try:
        parse(source)
    except TemplateError as exc:
        return str(exc)
    return None


__all__ = ["TemplateError", "lookup", "parse", "render", "validate"]
