"""Ages at death per member: fixed by the scenario, expected from the life table, or drawn per Monte Carlo path."""

from __future__ import annotations

from collections.abc import Sequence

from northward.config.household import Member
from northward.config.loader import SimulationInput
from northward.config.scenario import FixedMortality, SampledMortality


def age_at_start(member: Member, start_year: int) -> float:
    """Exact age on January 1 of `start_year` (birthdays fall on the first of the birth month)."""
    return start_year - member.birth_year - (member.birth_month - 1) / 12


def is_sampled(sim: SimulationInput) -> bool:
    return isinstance(sim.scenario.levers.mortality, SampledMortality)


def planned_death_ages(sim: SimulationInput) -> dict[str, float]:
    """Death ages for a deterministic run: the scenario's fixed ages, each member's life expectancy when mortality is
    sampled, or none (everyone reaches the horizon)."""
    mortality = sim.scenario.levers.mortality
    if isinstance(mortality, FixedMortality):
        return dict(mortality.death_ages)
    if isinstance(mortality, SampledMortality):
        table, start = sim.rules.mortality, sim.scenario.horizon.start_year
        return {
            m.id: round(table.expected_death_age(m.sex, age_at_start(m, start)) * 12) / 12
            for m in sim.profile.household.members
        }
    return {}


def sampled_death_ages(sim: SimulationInput, uniforms: Sequence[float]) -> dict[str, float]:
    """Death ages from one uniform draw per member (in household order), by inverting the life table."""
    table, start = sim.rules.mortality, sim.scenario.horizon.start_year
    members = sim.profile.household.members
    return {m.id: table.death_age(m.sex, age_at_start(m, start), u) for m, u in zip(members, uniforms, strict=True)}
