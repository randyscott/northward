import pytest
from pydantic import ValidationError

from northward.config.income import IncomeDoc, PensionStream, SalaryStream
from northward.config.liabilities import LiabilitiesDoc
from northward.config.spending import SpendingDoc
from tests.conftest import load_yaml


def test_example_income_parses_stream_types():
    doc = IncomeDoc.model_validate(load_yaml("profiles/example/income.yaml"))
    by_id = {s.id: s for s in doc.income_streams}
    assert isinstance(by_id["jordan_salary"], SalaryStream)
    assert by_id["jordan_salary"].elections.dependent_care_fsa.annual == 5000
    assert isinstance(by_id["alex_pension"], PensionStream)


def test_fsa_election_only_on_salary():
    data = load_yaml("profiles/example/income.yaml")
    data["income_streams"][2]["elections"] = {"dependent_care_fsa": {"annual": 1000}}
    with pytest.raises(ValidationError, match="elections"):
        IncomeDoc.model_validate(data)


def test_empty_liabilities_key_means_no_liabilities():
    assert LiabilitiesDoc.model_validate({"schema_version": 1, "liabilities": None}).liabilities == ()


def test_amortizing_loan_needs_exactly_one_of_payment_or_term():
    loan = {"id": "l", "kind": "amortizing", "balance": 1000, "annual_rate": 0.05}
    with pytest.raises(ValidationError, match="exactly one"):
        LiabilitiesDoc.model_validate({"schema_version": 1, "liabilities": [loan]})


def test_amortizing_payment_must_cover_interest():
    loan = {"id": "l", "kind": "amortizing", "balance": 300000, "annual_rate": 0.06, "monthly_payment": 1000}
    with pytest.raises(ValidationError, match="never pays off"):
        LiabilitiesDoc.model_validate({"schema_version": 1, "liabilities": [loan]})


def spending(**category):
    return {
        "schema_version": 1,
        "spending": {"base": {"amount": 1000}, "categories": [{"id": "c", "amount": 1, **category}]},
    }


def test_example_spending_loads():
    doc = SpendingDoc.model_validate(load_yaml("profiles/example/spending.yaml"))
    assert doc.spending.base.phases.bands[-1].until_age is None
    assert {c.id for c in doc.spending.categories} >= {"sam_college", "car_replacement", "roof"}


def test_once_is_exclusive():
    with pytest.raises(ValidationError, match="'once' can't be combined"):
        SpendingDoc.model_validate(spending(once={"year": 2030}, every_years=3))


def test_qualified_education_needs_beneficiary():
    with pytest.raises(ValidationError, match="must name a beneficiary"):
        SpendingDoc.model_validate(spending(tags=["qualified_education"]))


def test_phase_bands_must_end_open_and_increase():
    data = spending()
    data["spending"]["base"]["phases"] = {"reference": "a", "bands": [{"until_age": 80, "multiplier": 1}]}
    with pytest.raises(ValidationError, match="last phase band must omit until_age"):
        SpendingDoc.model_validate(data)
    data["spending"]["base"]["phases"]["bands"] = [
        {"until_age": 80, "multiplier": 1},
        {"until_age": 75, "multiplier": 1},
        {"multiplier": 1},
    ]
    with pytest.raises(ValidationError, match="must increase"):
        SpendingDoc.model_validate(data)


def salary_with(elections):
    return {
        "schema_version": 1,
        "income_streams": [{"id": "s", "owner": "a", "type": "salary", "amount": 100000, "elections": elections}],
    }


@pytest.mark.parametrize(
    ("deferral", "message"),
    [
        ({"account": "k"}, "exactly one of percent, amount, or max"),
        ({"account": "k", "percent": 0.1, "max": True}, "exactly one of percent, amount, or max"),
        ({"account": "k", "max": True, "roth_catch_up_account": "r"}, "only applies when include_catch_up"),
    ],
)
def test_retirement_deferral_shape(deferral, message):
    with pytest.raises(ValidationError, match=message):
        IncomeDoc.model_validate(salary_with({"retirement_deferrals": [deferral]}))


def test_only_one_max_deferral_per_salary():
    deferrals = [{"account": "k", "max": True}, {"account": "r", "max": True}]
    with pytest.raises(ValidationError, match="only one retirement deferral may use max"):
        IncomeDoc.model_validate(salary_with({"retirement_deferrals": deferrals}))


def test_match_tiers_must_increase():
    match = {"account": "k", "tiers": [{"match": 1, "up_to": 0.06}, {"match": 0.5, "up_to": 0.03}]}
    with pytest.raises(ValidationError, match="must increase"):
        IncomeDoc.model_validate(salary_with({"employer_match": match}))


def test_hsa_election_needs_an_amount_or_max():
    with pytest.raises(ValidationError, match="exactly one"):
        IncomeDoc.model_validate(salary_with({"hsa": {"account": "h", "coverage": "family"}}))
