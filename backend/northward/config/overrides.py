"""Dotted-path patches applied to raw document data before validation."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any


class OverrideError(ValueError):
    pass


def apply_overrides(data: Any, overrides: Mapping[str, Any]) -> Any:
    """Return a deep copy of `data` with each `path: value` applied.

    Path segments are mapping keys, or, for lists, the `id` (or `name`) of an item or its numeric index.
    Every segment but the last must already exist; the last may add a new mapping key.
    """
    result = copy.deepcopy(data)
    for path, value in overrides.items():
        _set(result, path, value)
    return result


def _set(root: Any, path: str, value: Any) -> None:
    tokens = path.split(".")
    if not path or any(not t for t in tokens):
        raise OverrideError(f"invalid override path '{path}'")
    node = root
    for depth, token in enumerate(tokens):
        last = depth == len(tokens) - 1
        parent = ".".join(tokens[:depth]) or "the document root"
        if isinstance(node, list):
            index = _find_item(node, token)
            if index is None:
                raise OverrideError(f"override '{path}': no item '{token}' in {parent}")
            if last:
                node[index] = value
                return
            node = node[index]
        elif isinstance(node, dict):
            if last:
                node[token] = value
                return
            if token not in node:
                raise OverrideError(f"override '{path}': '{token}' not found in {parent}")
            node = node[token]
        else:
            raise OverrideError(f"override '{path}': {parent} is not a mapping or list")


def _find_item(items: list[Any], token: str) -> int | None:
    for index, item in enumerate(items):
        if isinstance(item, dict) and token in (item.get("id"), item.get("name")):
            return index
    if token.isdigit() and int(token) < len(items):
        return int(token)
    return None
