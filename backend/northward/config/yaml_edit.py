"""Writing structured (JSON-like) data back into a YAML document without losing its comments (PLAN.md D18).

`merge_into_yaml(text, data)` returns `text` with its values replaced by `data`: unchanged values keep their exact
formatting, comments, and key order; new keys are appended; keys missing from `data` are removed. List items that
have an `id` are matched by id, so comments stay with the right item when items are reordered or inserted.
"""

from __future__ import annotations

import io
from typing import Any

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq


def _yaml() -> YAML:
    handler = YAML()  # round-trip mode
    handler.preserve_quotes = True
    handler.width = 4096  # never re-wrap long lines
    handler.indent(mapping=2, sequence=4, offset=2)  # the data/ files' style: "key:\n  - item"
    return handler


def _same(a: Any, b: Any) -> bool:
    """Equal data, counting booleans as different from numbers (in Python, True == 1)."""
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    return isinstance(a, bool) == isinstance(b, bool) and a == b


def _merge(old: Any, new: Any) -> Any:
    if isinstance(old, CommentedMap) and isinstance(new, dict):
        for key in [k for k in old if k not in new]:
            del old[key]
        for key, value in new.items():
            old[key] = _merge(old[key], value) if key in old else value
        return old
    if isinstance(old, CommentedSeq) and isinstance(new, list):
        return _merge_list(old, new)
    if not isinstance(old, (dict, list)) and old == new and isinstance(old, bool) == isinstance(new, bool):
        return old  # an equal scalar keeps its original spelling and quoting
    return new


def _ids(items: list[Any]) -> list[Any]:
    return [item.get("id") if isinstance(item, dict) else None for item in items]


def _merge_list(old: CommentedSeq, new: list[Any]) -> CommentedSeq:
    if _ids(old) == _ids(new):  # the same items in the same order (without ids: the same number of items)
        for index, item in enumerate(new):
            old[index] = _merge(old[index], item)
        return old
    by_id = {item["id"]: item for item in old if isinstance(item, CommentedMap) and "id" in item}
    merged = [_merge(by_id[i], item) if i in by_id else item for i, item in zip(_ids(new), new, strict=True)]
    # Blank lines and comments before an item can be stored on the list, keyed by the item's position (the rest
    # live inside the items). Move them with their items; items without one get the usual separator.
    leading = {id(old[index]): comment for index, comment in old.ca.items.items() if index < len(old)}
    first = id(old[0]) if len(old) else None
    separator = next(iter(leading.values()), None)
    old.clear()
    old.ca.items.clear()
    old.extend(merged)
    for index, item in enumerate(merged):
        if index == 0:
            comment = leading.get(id(item)) if id(item) == first else None
        else:
            comment = leading.get(id(item), separator)
        if comment is not None:
            old.ca.items[index] = comment
    return old


def merge_into_yaml(text: str | None, data: dict[str, Any]) -> str:
    """YAML text holding `data`, keeping as much of `text` (comments, order, formatting) as still applies."""
    if text is not None:
        try:
            if _same(yaml.safe_load(text), data):
                return text
        except yaml.YAMLError:
            text = None
    handler = _yaml()
    document = handler.load(text) if text else None
    merged = _merge(document, data) if isinstance(document, CommentedMap) else data
    out = io.StringIO()
    handler.dump(merged, out)
    return out.getvalue()
