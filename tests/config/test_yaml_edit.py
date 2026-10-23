import pytest
import yaml

from northward.config.yaml_edit import merge_into_yaml
from tests.conftest import DATA_DIR

TEXT = """\
schema_version: 1
# Accounts, oldest first.
accounts:
  - id: a          # the first one
    balance: 1_000
    rate: 0.050
    strategy: {kind: static, stocks: 0.6}

  - id: b
    balance: 2000
    note: "quoted"
"""


def merged(change) -> str:
    data = yaml.safe_load(TEXT)
    change(data)
    out = merge_into_yaml(TEXT, data)
    assert yaml.safe_load(out) == data
    return out


@pytest.mark.parametrize("path", sorted((DATA_DIR / "profiles" / "example").rglob("*.yaml")), ids=lambda p: p.name)
def test_unchanged_data_gives_back_the_text_exactly(path):
    text = path.read_text()
    assert merge_into_yaml(text, yaml.safe_load(text)) == text


def test_a_changed_value_changes_only_its_line():
    out = merged(lambda d: d["accounts"][1].update(balance=2500))
    assert out == TEXT.replace("balance: 2000", "balance: 2500")


def test_equal_values_keep_their_spelling_and_quotes():
    out = merged(lambda d: d["accounts"][1].update(balance=2001))
    assert "balance: 1_000" in out and "rate: 0.050" in out and 'note: "quoted"' in out
    assert "strategy: {kind: static, stocks: 0.6}" in out


def test_keys_can_be_added_and_removed():
    def change(d):
        del d["accounts"][1]["note"]
        d["accounts"][0]["owner"] = "joint"

    out = merged(change)
    assert "note:" not in out and "owner: joint" in out and "# the first one" in out


def test_list_items_keep_their_comments_when_reordered_or_inserted():
    out = merged(lambda d: d["accounts"].reverse())
    assert out.index("id: b") < out.index("id: a          # the first one")
    out = merged(lambda d: d["accounts"].insert(1, {"id": "c", "balance": 5}))
    assert out.index("id: a") < out.index("id: c") < out.index("id: b")
    assert "# Accounts, oldest first." in out and "# the first one" in out


def test_a_new_document_or_unparsable_text_is_written_fresh():
    assert yaml.safe_load(merge_into_yaml(None, {"schema_version": 1, "x": [1, 2]})) == {
        "schema_version": 1,
        "x": [1, 2],
    }
    assert yaml.safe_load(merge_into_yaml("key: [unclosed", {"schema_version": 1})) == {"schema_version": 1}


def test_booleans_and_numbers_aren_t_confused():
    assert merge_into_yaml("flag: true\ncount: 1\n", {"flag": 1, "count": True}) == "flag: 1\ncount: true\n"
