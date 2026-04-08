---
title: "Overview"
---

# Yieldo Scoring Framework

_This page explains what the Yieldo Score is and how to read it. If you want to understand what goes into the score, continue to_ [_The Four Dimensions_](page-2-four-dimensions.md)_. If you're a developer or DeFi-native reader looking for the full technical model, jump to the_ [_Technical Deep-Dive_](page-6-scoring-model.md)_._

## What is the Yieldo Score?

The Yieldo Score is a number between 0 and 100 that tells you how safe and reliable a DeFi yield vault is — before you deposit a single dollar.

It is not a recommendation. It is not investment advice. It is a signal: a structured, independent assessment of a vault's safety, stability, and track record, calculated automatically from on-chain data.

Every score is broken into four parts — Capital, Performance, Risk, and Trust — so you always know exactly what is driving the number. There are no black boxes.

---

## Why it exists

Most DeFi yield vaults advertise an APY. Almost none tell you what happens if something goes wrong.

The result is a trust problem: wallets can't easily verify which vaults are well-managed, which are fragile, and which are farming short-term deposits with incentive emissions that will eventually run out. The information exists on-chain — it just isn't surfaced in a way that's usable.

Yieldo exists to fix that. Not by telling you what to do, but by giving you the information to decide for yourself.

---

## What the Yieldo Score is not

**The Yieldo Score is not investment advice.** A high score means a vault has demonstrated stability and safety by historical and current on-chain data. It does not guarantee future performance or protect against all risks. DeFi carries inherent risks that no scoring system can fully eliminate.

The score is also not influenced by vault platforms or curators. Yieldo does not accept listing fees. No vault can pay to improve its score. The only path to a higher score is a better, safer vault.

---

## Three things you see on every vault

Every vault on Yieldo shows three layers of information:

**Metrics** are the raw numbers: TVL, current APY, how long depositors typically stay, whether the yield is organic or incentivised. These are the facts — you read them and compare.

**Flags** are alerts that draw your attention to something important. A red flag means something is wrong right now. A yellow flag means conditions are deteriorating and worth watching. A blue flag is informational — not dangerous, but relevant.

**The Yieldo Score** is the composite number that combines everything into a single 0–100 signal, weighted by what matters most for capital safety.

---

## What the score means

| Score | What it means |
| --- | --- |
| **80 – 100** | Strong across all dimensions. Well-established vault with a solid safety and performance track record. |
| **60 – 79** | Solid fundamentals with some areas to watch. Suitable for most users depending on risk tolerance. |
| **40 – 59** | Mixed signals. May be a newer vault, a vault with elevated risk factors, or one with limited data history. |
| **Below 40** | Significant concerns in one or more dimensions. Approach with caution and review the flags carefully. |

**New vaults score lower by design.** A vault that launched two weeks ago doesn't have enough history to be assessed reliably. We apply a confidence discount to young vaults and show you exactly how old the vault is. This is intentional — we'd rather give you an honest score than a falsely confident one.

---

## Wallet presets

When a wallet integrates Yieldo, it selects a preset that determines which vaults are shown to its users by default. There are three:

| Preset | Minimum Score | Best for |
| --- | --- | --- |
| 🛡️ **Conservative** | 80\+ | Institutional wallets, users prioritising capital protection above all else |
| ⚖️ **Balanced** | 60\+ | General purpose wallets, most everyday users |
| 🚀 **Aggressive** | 40\+ | DeFi-native users comfortable with higher risk for higher potential return |

Wallets can customise these thresholds. Presets exist to make the default experience appropriate for each wallet's user base — not to restrict what experienced users can access.