import type { RiskProfileId } from "./types";

export const riskProfiles: {
  id: RiskProfileId;
  label: string;
  lambda: number;
  alpha: number;
  description: string;
}[] = [
  {
    id: "risk_neutral",
    label: "Risk Neutral",
    lambda: 0.0,
    alpha: 0.10,
    description: "maximize expected value with no tail weighting",
  },
  {
    id: "balanced",
    label: "Balanced",
    lambda: 0.35,
    alpha: 0.10,
    description: "blend expected profit with moderate tail protection",
  },
  {
    id: "defensive",
    label: "Defensive",
    lambda: 0.60,
    alpha: 0.10,
    description: "place more weight on downside control",
  },
  {
    id: "tail_hedged",
    label: "Tail Hedged",
    lambda: 0.80,
    alpha: 0.05,
    description: "focus strongly on the worst tail outcomes",
  },
  {
    id: "custom",
    label: "Custom",
    lambda: 0.35,
    alpha: 0.10,
    description: "manually choose lambda and alpha",
  },
];

export function getRiskProfile(id: RiskProfileId) {
  return riskProfiles.find((profile) => profile.id === id) ?? riskProfiles[1];
}
