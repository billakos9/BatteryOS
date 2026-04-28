from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass(frozen=True)
class BatteryProfile:
    name: str
    technology: str
    power_mw: float
    energy_mwh: float
    soc_min_mwh: float
    soc_max_mwh: float
    initial_soc_mwh: float
    charge_efficiency: float
    discharge_efficiency: float
    self_discharge_per_hour: float = 0.0
    max_cycles_per_day: float = 1.5
    degradation_cost_eur_per_mwh: float = 2.0
    terminal_soc_mwh: Optional[float] = None

    def __post_init__(self) -> None:
        if self.power_mw <= 0:
            raise ValueError("power_mw must be > 0")
        if self.energy_mwh <= 0:
            raise ValueError("energy_mwh must be > 0")
        if not 0 <= self.soc_min_mwh < self.soc_max_mwh <= self.energy_mwh:
            raise ValueError("require 0 <= soc_min < soc_max <= energy_mwh")
        if not self.soc_min_mwh <= self.initial_soc_mwh <= self.soc_max_mwh:
            raise ValueError("initial_soc must lie within [soc_min, soc_max]")
        for eta in (self.charge_efficiency, self.discharge_efficiency):
            if not 0 < eta <= 1:
                raise ValueError("efficiencies must lie in (0, 1]")
        if self.max_cycles_per_day < 0:
            raise ValueError("max_cycles_per_day must be >= 0")
        if self.degradation_cost_eur_per_mwh < 0:
            raise ValueError("degradation_cost must be >= 0")

    @property
    def round_trip_efficiency(self) -> float:
        return self.charge_efficiency * self.discharge_efficiency

    @property
    def usable_energy_mwh(self) -> float:
        return self.soc_max_mwh - self.soc_min_mwh

    @property
    def duration_hours(self) -> float:
        return self.energy_mwh / self.power_mw

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "BatteryProfile":
        energy = float(data["energy_mwh"])
        soc_min = data.get("soc_min_mwh")
        soc_max = data.get("soc_max_mwh")
        if soc_min is None:
            soc_min = float(data["soc_min_frac"]) * energy
        if soc_max is None:
            soc_max = float(data["soc_max_frac"]) * energy
        initial = data.get("initial_soc_mwh")
        if initial is None:
            initial = float(data.get("initial_soc_frac", 0.5)) * energy

        return cls(
            name=name,
            technology=data.get("technology", "unknown"),
            power_mw=float(data["power_mw"]),
            energy_mwh=energy,
            soc_min_mwh=float(soc_min),
            soc_max_mwh=float(soc_max),
            initial_soc_mwh=float(initial),
            charge_efficiency=float(data["charge_efficiency"]),
            discharge_efficiency=float(data["discharge_efficiency"]),
            self_discharge_per_hour=float(data.get("self_discharge_per_hour", 0.0)),
            max_cycles_per_day=float(data.get("max_cycles_per_day", 1.5)),
            degradation_cost_eur_per_mwh=float(data.get("degradation_cost_eur_per_mwh", 2.0)),
            terminal_soc_mwh=data.get("terminal_soc_mwh"),
        )


def load_profile(path: str | Path, name: str) -> BatteryProfile:
    with open(path, "r") as f:
        catalog = yaml.safe_load(f)
    profiles = catalog.get("profiles", catalog)
    if name not in profiles:
        raise KeyError(f"profile {name!r} not found in {path}")
    return BatteryProfile.from_dict(name, profiles[name])
