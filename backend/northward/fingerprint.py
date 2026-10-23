"""The engine version that runs are tagged with, so a cached result is reused only by the same simulation code."""

from __future__ import annotations

import functools
import hashlib
from pathlib import Path

from northward import __version__

# Code that can't change a simulated result: the command line, the API, and storage.
_EXCLUDED = frozenset({"cli.py", "api", "persistence"})


@functools.cache
def engine_version() -> str:
    """The package version plus a hash of the simulation source, e.g. `0.1.0+3f2a9c1b7d4e`."""
    root = Path(__file__).parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if relative.parts[0] in _EXCLUDED:
            continue
        digest.update(relative.as_posix().encode())
        digest.update(path.read_bytes())
    return f"{__version__}+{digest.hexdigest()[:12]}"
