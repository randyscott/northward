"""Document schema versions and the upgrade functions that bring older stored documents to the current schema.

When a document's schema changes incompatibly, bump its entry in CURRENT_SCHEMA_VERSIONS and register an upgrade:

    @register_upgrade("accounts", from_version=1)
    def _accounts_v1_to_v2(data: dict) -> dict:
        ...
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from northward.config.source import PROFILE_KINDS, RULE_KINDS, SCENARIO_KIND

Upgrade = Callable[[dict[str, Any]], dict[str, Any]]

CURRENT_SCHEMA_VERSIONS: dict[str, int] = {kind: 1 for kind in (*RULE_KINDS, *PROFILE_KINDS, SCENARIO_KIND)}

_UPGRADES: dict[tuple[str, int], Upgrade] = {}


def register_upgrade(kind: str, from_version: int) -> Callable[[Upgrade], Upgrade]:
    def decorator(fn: Upgrade) -> Upgrade:
        _UPGRADES[(kind, from_version)] = fn
        return fn

    return decorator


def upgrade_document(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    """Return `data` upgraded to the current schema version for `kind`. Raises ValueError if that's impossible."""
    version = data.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise ValueError("schema_version is missing or not an integer")
    current = CURRENT_SCHEMA_VERSIONS[kind]
    if version > current:
        raise ValueError(f"schema_version {version} is newer than this version of northward supports ({current})")
    data = copy.deepcopy(data)
    while version < current:
        upgrade = _UPGRADES.get((kind, version))
        if upgrade is None:
            raise ValueError(f"no upgrade registered for {kind} schema_version {version}")
        data = upgrade(data)
        version += 1
        data["schema_version"] = version
    return data
