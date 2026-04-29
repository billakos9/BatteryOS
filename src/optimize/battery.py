from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional

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
    max_cycles_per_year: float = 547.5
    lifetime_cycles_eol: float = 5000.0
    initial_cycle_count: float = 0.0
    degradation_cost_eur_per_mwh: float = 2.0
    transaction_cost_eur_per_mwh: float = 0.0
    eol_soh_threshold: float = 0.80
    soh_model: str = "linear"
    cost_escalation_factor: float = 2.0
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
        if self.max_cycles_per_year < 0:
            raise ValueError("max_cycles_per_year must be >= 0")
        if self.lifetime_cycles_eol <= 0:
            raise ValueError("lifetime_cycles_eol must be > 0")
        if self.initial_cycle_count < 0:
            raise ValueError("initial_cycle_count must be >= 0")
        if not 0 < self.eol_soh_threshold <= 1.0:
            raise ValueError("eol_soh_threshold must lie in (0, 1]")
        if self.soh_model not in ("linear", "sqrt"):
            raise ValueError("soh_model must be 'linear' or 'sqrt'")
        if self.cost_escalation_factor < 1.0:
            raise ValueError("cost_escalation_factor must be >= 1.0")
        if self.degradation_cost_eur_per_mwh < 0:
            raise ValueError("degradation_cost must be >= 0")
        if self.transaction_cost_eur_per_mwh < 0:
            raise ValueError("transaction_cost must be >= 0")
        if not 0 <= self.self_discharge_per_hour < 1:
            raise ValueError(
                f"self_discharge_per_hour must lie in [0, 1), got {self.self_discharge_per_hour}"
            )
        if self.terminal_soc_mwh is not None:
            if not self.soc_min_mwh <= self.terminal_soc_mwh <= self.soc_max_mwh:
                raise ValueError(
                    f"terminal_soc_mwh ({self.terminal_soc_mwh}) must lie within "
                    f"[soc_min, soc_max] = [{self.soc_min_mwh}, {self.soc_max_mwh}]"
                )

    @property
    def round_trip_efficiency(self) -> float:
        return self.charge_efficiency * self.discharge_efficiency

    @property
    def usable_energy_mwh(self) -> float:
        return self.soc_max_mwh - self.soc_min_mwh

    @property
    def duration_hours(self) -> float:
        return self.energy_mwh / self.power_mw

    def to_dict(self, fractions: bool = True) -> dict:
        """Serialize to a dict suitable for YAML round-trip.

        With fractions=True (default), SoC fields are written as fractions
        of energy_mwh — matching the bundled YAML style.
        """
        d: dict = {
            "technology": self.technology,
            "power_mw": self.power_mw,
            "energy_mwh": self.energy_mwh,
            "charge_efficiency": self.charge_efficiency,
            "discharge_efficiency": self.discharge_efficiency,
            "self_discharge_per_hour": self.self_discharge_per_hour,
            "max_cycles_per_day": self.max_cycles_per_day,
            "max_cycles_per_year": self.max_cycles_per_year,
            "lifetime_cycles_eol": self.lifetime_cycles_eol,
            "initial_cycle_count": self.initial_cycle_count,
            "degradation_cost_eur_per_mwh": self.degradation_cost_eur_per_mwh,
            "transaction_cost_eur_per_mwh": self.transaction_cost_eur_per_mwh,
            "eol_soh_threshold": self.eol_soh_threshold,
            "soh_model": self.soh_model,
            "cost_escalation_factor": self.cost_escalation_factor,
        }
        if fractions:
            d["soc_min_frac"] = self.soc_min_mwh / self.energy_mwh
            d["soc_max_frac"] = self.soc_max_mwh / self.energy_mwh
            d["initial_soc_frac"] = self.initial_soc_mwh / self.energy_mwh
        else:
            d["soc_min_mwh"] = self.soc_min_mwh
            d["soc_max_mwh"] = self.soc_max_mwh
            d["initial_soc_mwh"] = self.initial_soc_mwh
        if self.terminal_soc_mwh is not None:
            d["terminal_soc_mwh"] = self.terminal_soc_mwh
        return d

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
            max_cycles_per_year=float(data.get("max_cycles_per_year", 547.5)),
            lifetime_cycles_eol=float(data.get("lifetime_cycles_eol", 5000.0)),
            initial_cycle_count=float(data.get("initial_cycle_count", 0.0)),
            degradation_cost_eur_per_mwh=float(data.get("degradation_cost_eur_per_mwh", 2.0)),
            transaction_cost_eur_per_mwh=float(data.get("transaction_cost_eur_per_mwh", 0.0)),
            eol_soh_threshold=float(data.get("eol_soh_threshold", 0.80)),
            soh_model=str(data.get("soh_model", "linear")),
            cost_escalation_factor=float(data.get("cost_escalation_factor", 2.0)),
            terminal_soc_mwh=data.get("terminal_soc_mwh"),
        )

    @classmethod
    def custom(
        cls,
        name: str,
        power_mw: float,
        energy_mwh: float,
        *,
        technology: str = "custom",
        soc_min_frac: Optional[float] = None,
        soc_max_frac: Optional[float] = None,
        soc_min_mwh: Optional[float] = None,
        soc_max_mwh: Optional[float] = None,
        initial_soc_frac: float = 0.5,
        initial_soc_mwh: Optional[float] = None,
        charge_efficiency: float = 0.95,
        discharge_efficiency: float = 0.95,
        round_trip_efficiency: Optional[float] = None,
        self_discharge_per_hour: float = 0.0,
        max_cycles_per_day: float = 1.5,
        max_cycles_per_year: float = 547.5,
        lifetime_cycles_eol: float = 5000.0,
        initial_cycle_count: float = 0.0,
        degradation_cost_eur_per_mwh: float = 2.0,
        transaction_cost_eur_per_mwh: float = 0.0,
        eol_soh_threshold: float = 0.80,
        soh_model: str = "linear",
        cost_escalation_factor: float = 2.0,
        terminal_soc_mwh: Optional[float] = None,
    ) -> "BatteryProfile":
        """Build a custom battery from named arguments.

        Convenience for the framework user (battery owner) who wants to
        spin up an asset without writing YAML. All fields have sensible
        defaults; only `name`, `power_mw`, and `energy_mwh` are required.

        SoC limits accept either MWh or fraction-of-energy. If both are
        omitted the default safe band is [0.10, 0.90] for chemical
        batteries and [0.05, 0.95] for storage units (caller decides).
        Passing `round_trip_efficiency` overrides the per-direction
        efficiencies with sqrt(eta_rt) on each leg.
        """
        if soc_min_mwh is None:
            soc_min_mwh = (soc_min_frac if soc_min_frac is not None else 0.10) * energy_mwh
        if soc_max_mwh is None:
            soc_max_mwh = (soc_max_frac if soc_max_frac is not None else 0.90) * energy_mwh
        if initial_soc_mwh is None:
            initial_soc_mwh = initial_soc_frac * energy_mwh

        if round_trip_efficiency is not None:
            if not 0 < round_trip_efficiency <= 1:
                raise ValueError("round_trip_efficiency must lie in (0, 1]")
            half = round_trip_efficiency ** 0.5
            charge_efficiency = half
            discharge_efficiency = half

        return cls(
            name=name,
            technology=technology,
            power_mw=power_mw,
            energy_mwh=energy_mwh,
            soc_min_mwh=soc_min_mwh,
            soc_max_mwh=soc_max_mwh,
            initial_soc_mwh=initial_soc_mwh,
            charge_efficiency=charge_efficiency,
            discharge_efficiency=discharge_efficiency,
            self_discharge_per_hour=self_discharge_per_hour,
            max_cycles_per_day=max_cycles_per_day,
            max_cycles_per_year=max_cycles_per_year,
            lifetime_cycles_eol=lifetime_cycles_eol,
            initial_cycle_count=initial_cycle_count,
            degradation_cost_eur_per_mwh=degradation_cost_eur_per_mwh,
            transaction_cost_eur_per_mwh=transaction_cost_eur_per_mwh,
            eol_soh_threshold=eol_soh_threshold,
            soh_model=soh_model,
            cost_escalation_factor=cost_escalation_factor,
            terminal_soc_mwh=terminal_soc_mwh,
        )


def load_profile(path: str | Path | Iterable[str | Path], name: str) -> BatteryProfile:
    """Load a battery profile by name from one or more YAML files.

    Searches the given paths in order and returns the first match. This
    lets the bundled `config/storage_profiles.yaml` coexist with a
    user-managed file (e.g. `config/custom_profiles.yaml`) without
    editing the bundled catalog.
    """
    if isinstance(path, (str, Path)):
        paths: list[Path] = [Path(path)]
    else:
        paths = [Path(p) for p in path]

    seen: list[str] = []
    for p in paths:
        if not p.exists():
            continue
        with open(p, "r") as f:
            catalog = yaml.safe_load(f) or {}
        profiles = catalog.get("profiles", catalog)
        if not isinstance(profiles, dict):
            continue
        seen.extend(profiles.keys())
        if name in profiles:
            return BatteryProfile.from_dict(name, profiles[name])

    raise KeyError(
        f"profile {name!r} not found in {[str(p) for p in paths]}; "
        f"available: {sorted(set(seen)) or '<none>'}"
    )


def list_profiles(path: str | Path | Iterable[str | Path]) -> list[str]:
    """List the profile names available across one or more YAML files."""
    if isinstance(path, (str, Path)):
        paths: list[Path] = [Path(path)]
    else:
        paths = [Path(p) for p in path]
    names: list[str] = []
    for p in paths:
        if not p.exists():
            continue
        with open(p, "r") as f:
            catalog = yaml.safe_load(f) or {}
        profiles = catalog.get("profiles", catalog)
        if isinstance(profiles, dict):
            names.extend(profiles.keys())
    return sorted(set(names))


def save_profile(
    profile: BatteryProfile,
    path: str | Path,
    *,
    overwrite: bool = False,
    fractions: bool = True,
) -> None:
    """Append a battery profile to a YAML file (or create it).

    If the file exists, the profile is added under the `profiles:` key
    next to any others. If the same name already exists, set
    `overwrite=True` to replace it.
    """
    p = Path(path)
    if p.exists():
        with open(p, "r") as f:
            catalog = yaml.safe_load(f) or {}
    else:
        catalog = {}

    profiles = catalog.get("profiles")
    if not isinstance(profiles, dict):
        profiles = {}
        catalog["profiles"] = profiles

    if profile.name in profiles and not overwrite:
        raise KeyError(
            f"profile {profile.name!r} already exists in {path}; "
            f"pass overwrite=True to replace it"
        )

    profiles[profile.name] = profile.to_dict(fractions=fractions)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        yaml.safe_dump(catalog, f, sort_keys=False)
