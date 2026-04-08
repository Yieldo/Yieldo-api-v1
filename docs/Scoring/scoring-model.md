---
title: "Scoring Model"
---

# How the Score is Calculated

_This page explains the composite formula, dimension weights, confidence multiplier, flag penalties, and external rating bonus. If you want the plain-language explanation of what each dimension measures, see_ [_The Four Dimensions_](page-2-four-dimensions.md)_. If you want the data infrastructure behind the score, see_ [_Data Architecture_](page-7-data-architecture.md)_._

---

## The composite formula

```text
Final Score = (Capital × 0.20 + Performance × 0.20 + Risk × 0.35 + Trust × 0.25)
              × Confidence_Multiplier
              − Flag_Penalties
              + External_Rating_Bonus

Clamped to [0, 100]
```

Each dimension produces a sub-score between 0 and 100. Those sub-scores are weighted and combined into a raw score, adjusted by the Confidence Multiplier, reduced by any active flag penalties, and optionally increased by the External Rating Bonus. The result is always a whole number between 0 and 100.

---

## Dimension weights and rationale

| Dimension | Weight | What it asks | Why this weight |
| --- | --- | --- | --- |
| 🏦 Capital | 20% | Is this vault large enough and stable enough to trust? | TVL, flows, and depositor breadth establish whether the vault has sufficient scale to handle real capital. |
| 📈 Performance | 20% | Is the yield real, consistent, and competitive? | Reduced from 25% in v1. For stablecoin vaults, safety matters more than yield maximisation. Yield-chasers get burned. |
| 🛡️ Risk | 35% | Is capital protected from exploits, depegs, and emergencies? | The heaviest weight by design. For stablecoins, capital preservation is the primary objective. "Don't lose money" outranks everything. |
| 🤝 Trust | 25% | Are depositors staying, or farming and leaving? | Increased from 20% in v1. Retention and holding patterns are strong leading indicators of vault quality. Mercenary capital produces fragile vaults. |

Each dimension is composed of multiple underlying metrics. The specific metrics, their internal weights, and the scoring bands applied to each are part of the framework's implementation — not published, to prevent vault operators from optimising for the score rather than for the underlying quality the score is designed to measure. What is published is what each dimension measures, why it is weighted the way it is, and the full formula that combines them.

---

## Confidence Multiplier

Applied as a multiplier to the raw weighted score before flag penalties. Penalises vaults with insufficient data history rather than pretending confidence the data doesn't support.

| Vault Age | Multiplier | Effect |
| --- | --- | --- |
| Under 14 days | 0.50× | Score halved — almost no reliable data |
| 14–30 days | 0.65× | 35% discount — basic metrics available, risk history unreliable |
| 30–60 days | 0.80× | 20% discount — most metrics calculable |
| 60–90 days | 0.90× | 10% discount — near-complete picture |
| Over 90 days | 1.00× | Full score — all metrics reliable |

---

## Flag Penalties

Active flags subtract points from the score after the Confidence Multiplier is applied. A vault can accumulate multiple penalties simultaneously. The score is clamped to a minimum of 0.

| Flag | Severity | Penalty |
| --- | --- | --- |
| Emergency Withdraw | 🔴 Critical | −50 pts |
| Vault Paused | 🔴 Critical | −30 pts |
| Asset Depeg (Severe) | 🔴 Critical | −25 pts |
| TVL Crash | 🔴 Critical | −20 pts |
| Sustained Negative APY | 🔴 Critical | −20 pts |
| Withdrawal Queue Crisis | 🔴 Critical | −20 pts |
| Capital Flight | 🔴 Critical | −15 pts |
| Severely Below Benchmark | 🔴 Critical | −15 pts |
| Critically Few Depositors | 🔴 Critical | −15 pts |
| Extreme Incentive Dependency | 🔴 Critical | −10 pts |
| Very Short Avg Holding | 🔴 Critical | −10 pts |
| Asset Depeg (Moderate) | 🟡 Warning | −10 pts |
| TVL Drop | 🟡 Warning | −8 pts |
| Elevated Pending Withdrawals | 🟡 Warning | −8 pts |
| Net Outflow Elevated | 🟡 Warning | −5 pts |
| Low Depositor Count | 🟡 Warning | −5 pts |
| Negative APY (Single Day) | 🟡 Warning | −5 pts |
| High Incentive Ratio | 🟡 Warning | −5 pts |
| Capital Retention Declining | 🟡 Warning | −5 pts |
| Below Benchmark (Moderate) | 🟡 Warning | −5 pts |
| Short Avg Holding | 🟡 Warning | −3 pts |
| Info flags | 🔵 Info | 0 pts |

---

## External Rating Bonus

Applied additively after `raw × confidence − penalties`. Rewards vaults that have been independently assessed by recognised DeFi risk platforms. Capped at \+3 points — meaningful as a differentiator, not significant enough to mask underlying quality.

| Independent Ratings | Bonus |
| --- | --- |
| 3 or more | \+3 pts |
| 2 | \+1 pt |
| 0 or 1 | \+0 pts |

Recognised providers currently include Bluechip, Credora, DeFi Safety, and Exponential. Each provider counts once regardless of rating value or direction.

---

## Worked example

**Vault A** — Stablecoin vault on Ethereum, 120 days old.

| Dimension | Sub-score | Weight | Contribution |
| --- | --- | --- | --- |
| Capital | 82 | 20% | 16.4 |
| Performance | 85 | 20% | 17.0 |
| Risk | 87 | 35% | 30.5 |
| Trust | 81 | 25% | 20.3 |
| **Raw score** |  |  | **84.2** |

- Confidence Multiplier: **1.00** (vault is 120 days old — full score)
- Active flags: Incentivised Yield badge (🔵 Info — 0 pts penalty)
- Flag penalties: **0 pts**
- External Rating Bonus: **\+3 pts** (independently rated by 3 providers)

**Final Yieldo Score: 87 / 100**

---

**On methodology transparency.** The composite formula, dimension weights, confidence multiplier, flag penalties, and external rating bonus are all published here. The sub-metric composition within each dimension — the specific metrics measured, their internal weights, and the scoring bands applied — is not published. This boundary exists for one reason: publishing precise formulas would allow vault operators to optimise for the score rather than for the underlying quality the score measures. The framework is transparent about what it values and how it combines signals. The implementation detail that would enable gaming is kept internal.