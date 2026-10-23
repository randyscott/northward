import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from northward.persistence.db import Database
from northward.persistence.seed import seed

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"


@pytest.fixture
def data_dir() -> Path:
    return DATA_DIR


def load_yaml(relative: str) -> dict:
    """Parse a document from the repo's data/ tree."""
    return yaml.safe_load((DATA_DIR / relative).read_text())


@pytest.fixture(scope="session")
def example_data(tmp_path_factory) -> Path:
    """A data/ tree with the rules and only the committed example profile (a local real profile stays out)."""
    root = tmp_path_factory.mktemp("data")
    shutil.copytree(DATA_DIR / "rules", root / "rules")
    shutil.copytree(DATA_DIR / "profiles" / "example", root / "profiles" / "example")
    return root


@pytest.fixture(scope="session")
def seeded_template(tmp_path_factory, example_data) -> Path:
    path = tmp_path_factory.mktemp("template") / "northward.db"
    db = Database(f"sqlite:///{path}")
    db.migrate()
    seed(db, example_data)
    db.engine.dispose()
    return path


@pytest.fixture
def db(tmp_path, seeded_template) -> Iterator[Database]:
    """A migrated database seeded with the example data (a fresh copy per test)."""
    path = tmp_path / "northward.db"
    shutil.copy(seeded_template, path)
    database = Database(f"sqlite:///{path}")
    yield database
    database.engine.dispose()


@pytest.fixture
def empty_db(tmp_path) -> Iterator[Database]:
    """A database URL with nothing created yet."""
    database = Database(f"sqlite:///{tmp_path / 'empty' / 'northward.db'}")
    yield database
    database.engine.dispose()
