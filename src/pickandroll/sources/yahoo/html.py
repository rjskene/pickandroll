"""A small, forgiving DOM over the standard library's HTML parser: enough to read Yahoo's
server-rendered league pages without a third-party parser. Unclosed tags are closed by their
parent's end tag; stray end tags are ignored."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser

VOID = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "track",
        "wbr",
    }
)
#: Elements whose start closes an open one of the same kind, and the ancestors that stop the
#: search (a nested table's rows do not close the outer table's).
SELF_NESTING: dict[str, frozenset[str]] = {
    "tr": frozenset({"table", "thead", "tbody", "tfoot"}),
    "td": frozenset({"tr", "table"}),
    "th": frozenset({"tr", "table"}),
    "li": frozenset({"ul", "ol"}),
    "option": frozenset({"select"}),
}
SKIP = frozenset({"script", "style", "noscript", "svg"})
_SPACE = re.compile(r"\s+")


@dataclass
class Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[Node | str] = field(default_factory=list)

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def get(self, name: str, default: str | None = None) -> str | None:
        return self.attrs.get(name, default)

    def iter(self) -> Iterator[Node]:
        stack: list[Node] = [self]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(c for c in reversed(node.children) if isinstance(c, Node))

    def find_all(
        self,
        tag: str | None = None,
        cls: str | None = None,
        attr: str | None = None,
        pred: Callable[[Node], bool] | None = None,
    ) -> Iterator[Node]:
        for node in self.iter():
            if node is self:
                continue
            if tag is not None and node.tag != tag:
                continue
            if cls is not None and cls not in node.classes:
                continue
            if attr is not None and attr not in node.attrs:
                continue
            if pred is not None and not pred(node):
                continue
            yield node

    def find(self, *args, **kwargs) -> Node | None:
        return next(self.find_all(*args, **kwargs), None)

    def children_of(self, tag: str) -> list[Node]:
        return [c for c in self.children if isinstance(c, Node) and c.tag == tag]

    def text(self) -> str:
        """The element's text in document order, whitespace collapsed."""
        return _SPACE.sub(" ", "".join(_texts(self))).strip()


def _texts(node: Node) -> Iterator[str]:
    for child in node.children:
        if isinstance(child, str):
            yield child
        else:
            if child.tag in ("br", "td", "th", "div", "li", "tr", "h6", "p"):
                yield " "
            yield from _texts(child)
            if child.tag in ("span", "a", "td", "th", "div", "li"):
                yield " "


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#document")
        self.stack: list[Node] = [self.root]
        self.skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.skipping:
            if tag in SKIP:
                self.skipping += 1
            return
        if tag in SKIP:
            self.skipping = 1
            return
        if tag in SELF_NESTING:
            self._close_open(tag)
        node = Node(tag, {k: (v or "") for k, v in attrs})
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.skipping or tag in SKIP:
            return
        self.stack[-1].children.append(Node(tag, {k: (v or "") for k, v in attrs}))

    def handle_endtag(self, tag: str) -> None:
        if self.skipping:
            if tag in SKIP:
                self.skipping -= 1
            return
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data: str) -> None:
        if not self.skipping and data:
            self.stack[-1].children.append(data)

    def _close_open(self, tag: str) -> None:
        """A new ``<tr>`` (or ``<td>``...) closes the open one, as browsers do."""
        boundary = SELF_NESTING[tag]
        for i in range(len(self.stack) - 1, 0, -1):
            node = self.stack[i]
            if node.tag == tag:
                del self.stack[i:]
                return
            if node.tag in boundary:
                return


def parse(html: str) -> Node:
    builder = _Builder()
    builder.feed(html)
    builder.close()
    return builder.root


def table_rows(table: Node) -> tuple[list[str], list[Node]]:
    """A table's column labels (its last header row, colspans expanded) and its body rows."""
    head = table.find("thead")
    labels: list[str] = []
    if head is not None:
        rows = list(head.find_all("tr"))
        if rows:
            for th in rows[-1].children_of("th"):
                span = int(th.get("colspan") or 1)
                labels.extend([th.text()] * span)
    body = table.find("tbody") or table
    rows = [tr for tr in body.find_all("tr") if tr.children_of("td")]
    return labels, rows


def cells(row: Node) -> list[Node]:
    """A row's cells, colspans expanded so they line up with :func:`table_rows`' labels."""
    out: list[Node] = []
    for td in row.children_of("td"):
        out.extend([td] * int(td.get("colspan") or 1))
    return out
