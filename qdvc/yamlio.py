"""Reading and writing YAML with PyYAML's node API.

Composing (rather than loading) keeps key order and scalar text exactly as
written, so a project ID such as ``2612`` stays a string, and unknown keys
can be written back as they were read. Writing builds nodes with explicit
scalar styles and serialises them with the same layout the macOS edition
gets from Yams (both emitters descend from libyaml): two-space indents,
sequences in mappings not indented, no line folding, UTF-8 left as is.
"""

from __future__ import annotations

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode
from yaml.resolver import Resolver

STR_TAG = "tag:yaml.org,2002:str"
MAP_TAG = "tag:yaml.org,2002:map"
SEQ_TAG = "tag:yaml.org,2002:seq"

_resolver = Resolver()
_NULLS = {"", "~", "null", "Null", "NULL"}
_RESERVED = {"y", "n", "yes", "no", "true", "false", "on", "off", "null", "~"}
_INDICATORS = set("0123456789+-.:?!&*#|>'\"%@`,[]{}=")


class FileError(Exception):
    """A file that is not valid YAML, not a mapping, or not UTF-8."""


def mapping_pairs(text: str) -> list[tuple[str, Node]]:
    """The top-level mapping as (key, value) pairs in file order. An empty
    file is an empty mapping."""
    try:
        node = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError as e:
        first = str(e).split("\n", 1)[0]
        raise FileError(f"The file is not valid YAML ({first}).") from None
    if node is None:
        return []
    return pairs(node)


def pairs(node: Node) -> list[tuple[str, Node]]:
    if is_null(node):
        return []
    if not isinstance(node, MappingNode):
        raise FileError("The file does not hold a YAML mapping.")
    return [(k.value if isinstance(k, ScalarNode) else "", v) for k, v in node.value]


def is_null(node: Node) -> bool:
    return isinstance(node, ScalarNode) and node.style is None and node.value in _NULLS


def string(node: Node | None) -> str | None:
    """A scalar's text, or None for null and for non-scalars."""
    if not isinstance(node, ScalarNode) or is_null(node):
        return None
    return node.value


def integer(node: Node | None) -> int | None:
    s = string(node)
    if s is None:
        return None
    s = s.strip(" ")
    body = s[1:] if s[:1] in "+-" else s
    if not body or not body.isascii() or not body.isdigit():
        return None
    return int(s)


def boolean(node: Node | None) -> bool | None:
    s = string(node)
    if s is None:
        return None
    s = s.lower()
    if s in ("true", "yes", "on", "y"):
        return True
    if s in ("false", "no", "off", "n"):
        return False
    return None


def sequence(node: Node | None) -> list[Node]:
    """A sequence's items; a lone scalar counts as a one-item sequence."""
    if node is None:
        return []
    if isinstance(node, SequenceNode):
        return list(node.value)
    if is_null(node):
        return []
    return [node]


def one_line(s: str) -> str:
    """Lines joined with spaces, trimmed."""
    return " ".join(part for part in s.splitlines() if part).strip(" \t")


# --- building nodes -------------------------------------------------------

def plain(value: str) -> ScalarNode:
    """A plain scalar whose tag is what a reader will resolve it to, so the
    emitter keeps it plain (Yams' ``Tag(.implicit)``)."""
    return ScalarNode(_resolver.resolve(ScalarNode, value, (True, False)), value, style=None)


def key(k: str) -> ScalarNode:
    return plain(k)


def number(v: int) -> ScalarNode:
    return plain(str(v))


def flag(v: bool) -> ScalarNode:
    return plain("true" if v else "false")


def date(d) -> ScalarNode:
    return plain(d.isoformat())


def needs_quotes(s: str) -> bool:
    if not s or s != s.strip(" \t"):
        return True
    if s.lower() in _RESERVED:
        return True
    # Anything starting like a number, date, time or YAML indicator (a project
    # ID such as 26XY starts with a digit, so it is quoted).
    if s[0] in _INDICATORS:
        return True
    return ": " in s or " #" in s or s.endswith(":")


def text(s: str) -> ScalarNode:
    """A string in the plainest style that reads back as the same string in
    YAML 1.1 and 1.2 readers: literal (``|``) for several lines,
    single-quoted where a plain scalar would read as something else."""
    if "\n" in s:
        return ScalarNode(STR_TAG, s, style="|")
    if needs_quotes(s):
        return ScalarNode(STR_TAG, s, style="'")
    return plain(s)


def mapping(items: list[tuple[Node, Node]]) -> MappingNode:
    return MappingNode(MAP_TAG, items, flow_style=False)


def seq(items: list[Node]) -> SequenceNode:
    return SequenceNode(SEQ_TAG, items, flow_style=False)


def emit(node: Node) -> str:
    return yaml.serialize(node, Dumper=yaml.SafeDumper, allow_unicode=True,
                          width=1 << 30, indent=2, line_break="\n")
