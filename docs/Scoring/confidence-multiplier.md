---
title: "Confidence Multiplier"
---

# The Confidence Multiplier

_This page explains why new vaults score lower and what the maturity labels mean. It's a short read — most users only need this once._

---

## Honest about uncertainty

A vault that launched two weeks ago cannot be scored the same way as one that has been running for two years. The data simply isn't there yet. You can't calculate a meaningful risk-adjusted return with 14 days of history. You can't assess whether depositors stay long-term when no one has been depositing long enough to know.

Rather than pretend otherwise, the Yieldo Scoring Framework applies a **Confidence Multiplier** — a discount to the final score that reflects how much data is actually available. The younger the vault, the lower the multiplier, and the lower the resulting score.

This is intentional. A score that communicates honest uncertainty is more useful than a score that implies confidence the data doesn't support.

---

## The maturity ladder

| Vault Age | Multiplier | What it means |
| --- | --- | --- |
| Under 14 days | 0.50× | Score halved. Almost no data. Core metrics calculable, but no reliable risk or performance history. |
| 14 – 30 days | 0.65× | 35% discount. Basic yield figures available but volatility and risk metrics are unreliable. |
| 30 – 60 days | 0.80× | 20% discount. Most metrics calculable. Some longer-term signals still developing. |
| 60 – 90 days | 0.90× | 10% discount. Nearly full picture. Minor uncertainty remains. |
| Over 90 days | 1.00× | Full score. All metrics reliable, including risk-adjusted performance history. |

---

## What this looks like in practice

A vault with strong fundamentals — healthy TVL, good yield, solid depositor behaviour — might have a raw score of 78. If that vault is 20 days old, the Confidence Multiplier reduces that to approximately 51. The vault isn't bad. The data is just young.

This is why two vaults with similar characteristics can have very different scores: one may simply be newer. You'll always see the vault's age displayed alongside its score so you can factor this in yourself.

**A low score on a new vault is not a red flag.** It is a yellow flag of a different kind — not "something is wrong" but "we don't know enough yet." Some of the best vaults on the platform started with scores below 50. Give them 90 days, and a well-run vault will earn its full score on its own merits.

---

## Maturity badges

Every vault displays a badge that tells you at a glance where it sits on the maturity ladder:

- **New Vault** — under 30 days
- **Early** — 30 to 90 days
- **Established** — over 90 days (no badge shown — this is the default state)

Vaults in the New or Early stage also carry a 🔵 Info flag automatically. This flag carries no score penalty beyond the Confidence Multiplier — it is simply there to make sure the vault's limited history is visible to you before you deposit.