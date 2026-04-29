"""
BatteryStateTracker — cumulative degradation, rolling annual cycle budget,
and dynamic degradation cost for multi-year backtests.

Tracks:
- Cumulative equivalent full cycles (lifetime)
- Rolling 365-day cycle count (annual cap enforcement)
- State of Health (SOH) degradation
- Dynamic degradation cost that rises as battery ages
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
import pandas as pd

from src.optimize.battery import BatteryProfile


@dataclass
class BatteryState:
    """Snapshot of battery health on a given day."""

    date: str
    cumulative_cycles: float
    cycles_last_365_days: float
    soh_frac: float
    effective_energy_mwh: float
    effective_usable_energy_mwh: float
    dynamic_degradation_cost_eur_per_mwh: float
    annual_budget_remaining: float
    lifetime_budget_remaining: float
    is_eol: bool


class BatteryStateTracker:
    """
    Track battery degradation across a multi-year backtest.

    For each day, the tracker:
    1. Computes cycles used in the trailing 365 days
    2. Computes remaining annual budget
    3. Computes remaining lifetime budget
    4. Adjusts degradation cost based on age (optional)
    5. Returns an adjusted BatteryProfile for that day's optimization
    """

    def __init__(self, base_battery: BatteryProfile):
        """
        Parameters
        ----------
        base_battery : BatteryProfile
            The nominal battery specification. Degradation parameters
            (soh_model, cost_escalation_factor, eol_soh_threshold) are
            read directly from the profile.
        """
        self.base = base_battery
        self.soh_model = base_battery.soh_model
        self.cost_escalation_factor = base_battery.cost_escalation_factor
        self.eol_soh_threshold = base_battery.eol_soh_threshold

        # History of daily cycle usage
        self.daily_cycles: list[tuple[str, float]] = []

        # Carry-over SoC from previous day (starts at profile default)
        self.last_final_soc_mwh: float = base_battery.initial_soc_mwh

    def _compute_cycles_last_365(self, current_date: pd.Timestamp) -> float:
        """Sum cycles used in the 365 days preceding current_date."""
        if not self.daily_cycles:
            return 0.0
        cutoff = current_date - pd.Timedelta(days=365)
        total = 0.0
        for date_str, cycles in self.daily_cycles:
            d = pd.Timestamp(date_str)
            if cutoff <= d < current_date:
                total += cycles
        return total

    def _compute_soh(self, cumulative_cycles: float) -> float:
        """State of Health as fraction of original capacity."""
        if self.soh_model == "linear":
            # Linear degradation: SOH = 1 - (cycles / EOL_cycles)
            soh = 1.0 - (cumulative_cycles / self.base.lifetime_cycles_eol)
        elif self.soh_model == "sqrt":
            # Sqrt model: degradation accelerates later
            frac = cumulative_cycles / self.base.lifetime_cycles_eol
            soh = 1.0 - (frac ** 0.5)
        else:
            raise ValueError(f"Unknown soh_model: {self.soh_model}")
        return max(soh, 0.0)

    def _dynamic_degradation_cost(self, soh_frac: float) -> float:
        """
        Increase degradation cost as battery ages.
        At SOH=1.0: base cost
        At SOH=0.50: base cost * escalation_factor
        At SOH=0.00: base cost * escalation_factor^2
        """
        base = self.base.degradation_cost_eur_per_mwh
        # Exponential cost rise as SOH drops
        exponent = (1.0 - soh_frac) / 0.5  # 0 at SOH=1, 1 at SOH=0.5, 2 at SOH=0
        return base * (self.cost_escalation_factor ** exponent)

    def get_state(self, date_str: str) -> BatteryState:
        """Compute battery state for a given date."""
        current_date = pd.Timestamp(date_str)

        cumulative_cycles = (
            self.base.initial_cycle_count
            + sum(c for _, c in self.daily_cycles)
        )
        cycles_365 = self._compute_cycles_last_365(current_date)
        soh = self._compute_soh(cumulative_cycles)
        is_eol = soh < self.eol_soh_threshold

        annual_budget_remaining = max(
            0.0, self.base.max_cycles_per_year - cycles_365
        )
        lifetime_budget_remaining = max(
            0.0, self.base.lifetime_cycles_eol - cumulative_cycles
        )

        effective_energy = self.base.energy_mwh * soh
        effective_usable = self.base.usable_energy_mwh * soh

        dynamic_cost = self._dynamic_degradation_cost(soh)

        return BatteryState(
            date=date_str,
            cumulative_cycles=cumulative_cycles,
            cycles_last_365_days=cycles_365,
            soh_frac=soh,
            effective_energy_mwh=effective_energy,
            effective_usable_energy_mwh=effective_usable,
            dynamic_degradation_cost_eur_per_mwh=dynamic_cost,
            annual_budget_remaining=annual_budget_remaining,
            lifetime_budget_remaining=lifetime_budget_remaining,
            is_eol=is_eol,
        )

    def get_effective_battery(self, date_str: str) -> BatteryProfile:
        """
        Return a BatteryProfile adjusted for current health state.

        If the battery is at EOL, returns a profile with zero power
        (effectively disabling it).
        """
        state = self.get_state(date_str)

        if state.is_eol:
            # Battery is dead — zero power, zero usable energy
            return BatteryProfile(
                name=f"{self.base.name}_EOL",
                technology=self.base.technology,
                power_mw=0.0,
                energy_mwh=state.effective_energy_mwh,
                soc_min_mwh=0.0,
                soc_max_mwh=state.effective_energy_mwh,
                initial_soc_mwh=0.0,
                charge_efficiency=self.base.charge_efficiency,
                discharge_efficiency=self.base.discharge_efficiency,
                self_discharge_per_hour=self.base.self_discharge_per_hour,
                max_cycles_per_day=0.0,
                max_cycles_per_year=0.0,
                lifetime_cycles_eol=self.base.lifetime_cycles_eol,
                initial_cycle_count=state.cumulative_cycles,
                degradation_cost_eur_per_mwh=state.dynamic_degradation_cost_eur_per_mwh,
                transaction_cost_eur_per_mwh=self.base.transaction_cost_eur_per_mwh,
                eol_soh_threshold=self.base.eol_soh_threshold,
                soh_model=self.base.soh_model,
                cost_escalation_factor=self.base.cost_escalation_factor,
                terminal_soc_mwh=None,
            )

        # Adjust SoC limits proportionally to SOH
        soc_min = self.base.soc_min_mwh * state.soh_frac
        soc_max = self.base.soc_max_mwh * state.soh_frac
        # Carry-over final SoC from previous day, clamped to current degraded limits
        initial_soc = max(soc_min, min(soc_max, self.last_final_soc_mwh))

        return BatteryProfile(
            name=self.base.name,
            technology=self.base.technology,
            power_mw=self.base.power_mw,
            energy_mwh=state.effective_energy_mwh,
            soc_min_mwh=soc_min,
            soc_max_mwh=soc_max,
            initial_soc_mwh=initial_soc,
            charge_efficiency=self.base.charge_efficiency,
            discharge_efficiency=self.base.discharge_efficiency,
            self_discharge_per_hour=self.base.self_discharge_per_hour,
            max_cycles_per_day=self.base.max_cycles_per_day,
            max_cycles_per_year=state.annual_budget_remaining,
            lifetime_cycles_eol=state.lifetime_budget_remaining,
            initial_cycle_count=state.cumulative_cycles,
            degradation_cost_eur_per_mwh=state.dynamic_degradation_cost_eur_per_mwh,
            transaction_cost_eur_per_mwh=self.base.transaction_cost_eur_per_mwh,
            eol_soh_threshold=self.base.eol_soh_threshold,
            soh_model=self.base.soh_model,
            cost_escalation_factor=self.base.cost_escalation_factor,
            terminal_soc_mwh=self.base.terminal_soc_mwh,
        )

    def record_day(
        self, date_str: str, cycles_used: float, final_soc_mwh: float | None = None
    ) -> None:
        """Record cycle usage and final SoC for a completed day."""
        self.daily_cycles.append((date_str, cycles_used))
        if final_soc_mwh is not None:
            self.last_final_soc_mwh = final_soc_mwh

    def get_history_df(self) -> pd.DataFrame:
        """Return daily cycle usage history as a DataFrame."""
        rows = []
        for date_str, cycles in self.daily_cycles:
            state = self.get_state(date_str)
            rows.append(
                {
                    "date": date_str,
                    "cycles_used": cycles,
                    "cumulative_cycles": state.cumulative_cycles,
                    "cycles_last_365": state.cycles_last_365_days,
                    "soh_frac": state.soh_frac,
                    "annual_budget_remaining": state.annual_budget_remaining,
                    "lifetime_budget_remaining": state.lifetime_budget_remaining,
                    "dynamic_degradation_cost": state.dynamic_degradation_cost_eur_per_mwh,
                    "is_eol": state.is_eol,
                }
            )
        return pd.DataFrame(rows)
