import json

from northward.api.app import create_app
from tests.conftest import REPO_ROOT


def test_the_frontends_api_schema_is_current(db):
    """frontend/openapi.json (and the TypeScript types generated from it) must match the API: run `make api-types`."""
    committed = json.loads((REPO_ROOT / "frontend" / "openapi.json").read_text())
    assert committed == create_app(db).openapi(), "the API changed: run `make api-types`"
