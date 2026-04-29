"""Risk profile presets for the single public optimizer.

These presets are product-level labels over the optimizer's two
continuous risk knobs:

  - risk_aversion (lambda)
  - alpha (CVaR tail mass)

The backend remains the source of truth for the preset tuples so the UI
can render human-readable categories without inventing its own mapping.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskProfilePreset:
    key: str
    label: str
    risk_lambda: float
    risk_alpha: float
    description: str


RISK_PROFILE_PRESETS: dict[str, RiskProfilePreset] = {
    "risk_neutral": RiskProfilePreset(
        key="risk_neutral",
        label="Risk Neutral",
        risk_lambda=0.00,
        risk_alpha=0.10,
        description="maximize expected value with no tail weighting",
    ),
    "balanced": RiskProfilePreset(
        key="balanced",
        label="Balanced",
        risk_lambda=0.35,
        risk_alpha=0.10,
        description="blend expected profit with moderate tail protection",
    ),
    "defensive": RiskProfilePreset(
        key="defensive",
        label="Defensive",
        risk_lambda=0.60,
        risk_alpha=0.10,
        description="place more weight on downside control",
    ),
    "tail_hedged": RiskProfilePreset(
        key="tail_hedged",
        label="Tail Hedged",
        risk_lambda=0.80,
        risk_alpha=0.05,
        description="focus strongly on the worst tail outcomes",
    ),
}

DEFAULT_RISK_PROFILE = "balanced"
CUSTOM_RISK_PROFILE = "custom"


def resolve_risk_profile(
    risk_profile: str | None,
    risk_lambda: float | None,
    risk_alpha: float | None,
) -> tuple[str, str, float, float, str]:
    """Resolve either a preset profile or custom raw lambda/alpha values."""
    if risk_profile in (None, ""):
        if risk_lambda is None and risk_alpha is None:
            preset = RISK_PROFILE_PRESETS[DEFAULT_RISK_PROFILE]
            return (
                preset.key,
                preset.label,
                preset.risk_lambda,
                preset.risk_alpha,
                preset.description,
            )
        return (
            CUSTOM_RISK_PROFILE,
            "Custom",
            0.5 if risk_lambda is None else float(risk_lambda),
            0.10 if risk_alpha is None else float(risk_alpha),
            "user-defined lambda/alpha tuple",
        )

    if risk_profile == CUSTOM_RISK_PROFILE:
        return (
            CUSTOM_RISK_PROFILE,
            "Custom",
            0.5 if risk_lambda is None else float(risk_lambda),
            0.10 if risk_alpha is None else float(risk_alpha),
            "user-defined lambda/alpha tuple",
        )

    try:
        preset = RISK_PROFILE_PRESETS[risk_profile]
    except KeyError as exc:
        valid = ", ".join([*RISK_PROFILE_PRESETS.keys(), CUSTOM_RISK_PROFILE])
        raise ValueError(f"unknown risk_profile={risk_profile!r}; valid values: {valid}") from exc

    return (
        preset.key,
        preset.label,
        preset.risk_lambda,
        preset.risk_alpha,
        preset.description,
    )
