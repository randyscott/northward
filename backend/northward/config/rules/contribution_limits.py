"""Annual contribution and election limits for one base year."""

from __future__ import annotations

from pydantic import Field

from northward.config.base import ByFilingStatus, Document, Money, StrictModel, Year
from northward.config.rules.federal_tax import Metadata, PhaseOutRange


class ElectiveDeferral(StrictModel):
    """401(k)/403(b)/457 employee deferrals."""

    limit: Money
    catch_up_50: Money
    catch_up_60_63: Money  # replaces catch_up_50 in the years a participant turns 60-63
    indexed: bool = True
    rounding: Money = 500
    # Catch-ups must be Roth when prior-year FICA wages from the employer exceed this.
    roth_catch_up_wage_threshold: Money
    roth_catch_up_threshold_indexed: bool = True
    roth_catch_up_required_from: Year


class IraLimits(StrictModel):
    limit: Money  # traditional + Roth combined
    catch_up_50: Money
    indexed: bool = True
    rounding: Money = 500
    catch_up_rounding: Money = 100


class IraPhaseOuts(StrictModel):
    indexed: bool = True
    married_filing_separately_indexed: bool = False  # the 0-10,000 MFS range is statutory
    ranges: ByFilingStatus[PhaseOutRange]


class TraditionalIraDeduction(StrictModel):
    """Deduction phase-outs when covered by a workplace plan."""

    indexed: bool = True
    married_filing_separately_indexed: bool = False
    contributor_covered: ByFilingStatus[PhaseOutRange]
    spouse_covered_only: PhaseOutRange  # MFJ, contributor not covered but spouse is


class HsaLimits(StrictModel):
    self_only: Money
    family: Money
    catch_up_55: Money
    indexed: bool = True
    rounding: Money = 50
    catch_up_indexed: bool = False


class DependentCareFsaLimits(StrictModel):
    household_limit: Money
    married_filing_separately_limit: Money
    indexed: bool = False


class GiftTaxExclusion(StrictModel):
    annual_exclusion: Money  # per donee
    indexed: bool = True
    rounding: Money = 1000


class Plan529RothRollover(StrictModel):
    lifetime_cap: Money  # per beneficiary
    min_account_age_years: int = Field(gt=0)  # the account must be open more than this many years
    contribution_lookback_years: int = Field(ge=0)  # contributions this recent (and their earnings) can't roll over


class ContributionLimitsDoc(Document):
    metadata: Metadata
    elective_deferral: ElectiveDeferral
    annual_additions_limit: Money  # §415(c) total employee + employer, excluding catch-ups
    ira: IraLimits
    roth_ira_phase_out: IraPhaseOuts
    traditional_ira_deduction_phase_out: TraditionalIraDeduction
    hsa: HsaLimits
    dependent_care_fsa: DependentCareFsaLimits
    gift_tax: GiftTaxExclusion
    plan_529_roth_rollover: Plan529RothRollover
