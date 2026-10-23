import copy

import numpy as np
import pytest
from pydantic import ValidationError

from northward.config.rules.account_types import AccountType, AccountTypesDoc
from northward.config.rules.glide_paths import GlidePathsDoc
from northward.config.rules.market import FACTORS, MarketAssumptionsDoc, MarketPreset
from tests.conftest import load_yaml


def test_account_types_load():
    doc = AccountTypesDoc.model_validate(load_yaml("rules/account_types.yaml"))
    assert doc.get("plan_529").family.value == "education_529"
    assert doc.get("roth_401k").rmd_rule.value == "none"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"ownership_constraint": "joint_or_individual"}, "must be individually owned"),
        ({"withdrawal_tax": "none"}, "requires withdrawal_tax"),
        ({"rmd_rule": "inherited_10_year"}, "only valid for the inherited family"),
        ({"tax_wrapper": "taxable"}, "requires tax_wrapper"),
    ],
)
def test_account_type_consistency(changes, message):
    traditional_ira = load_yaml("rules/account_types.yaml")["account_types"][2]
    with pytest.raises(ValidationError, match=message):
        AccountType.model_validate({**traditional_ira, **changes})


def test_glide_paths_load():
    doc = GlidePathsDoc.model_validate(load_yaml("rules/glide_paths.yaml"))
    default = doc.get("linear_default")
    assert (default.start_equity, default.years_before, default.target_equity) == (0.9, 40, 0.5)


def test_market_presets_load_with_valid_correlations():
    doc = MarketAssumptionsDoc.model_validate(load_yaml("rules/market_assumptions.yaml"))
    assert [p.id for p in doc.presets] == ["forward_conservative", "historical_us", "bootstrap", "pessimistic"]
    matrix = doc.get("forward_conservative").correlation_matrix()
    assert matrix.shape == (len(FACTORS), len(FACTORS))
    assert np.allclose(matrix, matrix.T)
    assert matrix[FACTORS.index("cash"), FACTORS.index("inflation")] == 0.5


def preset(**changes):
    data = copy.deepcopy(load_yaml("rules/market_assumptions.yaml")["presets"][0])
    data.update(changes)
    return data


def test_market_preset_rejects_impossible_correlations():
    correlations = {"stocks": {"bonds": 0.9, "cash": 0.9}, "bonds": {"cash": -0.9}}
    with pytest.raises(ValidationError, match="positive semi-definite"):
        MarketPreset.model_validate(preset(correlations=correlations))


def test_market_preset_rejects_duplicate_pairs():
    with pytest.raises(ValidationError, match="given twice"):
        MarketPreset.model_validate(preset(correlations={"stocks": {"bonds": 0.1}, "bonds": {"stocks": 0.1}}))


def test_market_preset_requires_every_factor():
    data = preset()
    del data["factors"]["cash"]
    with pytest.raises(ValidationError, match="factors missing: cash"):
        MarketPreset.model_validate(data)
