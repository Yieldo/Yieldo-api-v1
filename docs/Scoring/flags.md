---
title: "Flags"
---

# Flags

_This page explains what flags are and how to read them. If you want the full flag specification including trigger conditions, score penalties, and auto-clear logic, skip to the_ [_Technical Deep-Dive_](page-6-scoring-model.md)_._

## What flags are

Flags are alerts that appear on vault cards when the scoring engine detects something worth your attention. They sit alongside the Yieldo Score rather than replacing it — because a single number can't always communicate urgency.

Some situations require immediate visibility regardless of the underlying score. If a vault is paused right now, you need to know that instantly. Flags provide that layer of real-time signal.

---

## Three severity levels

### 🔴 Critical

Something is wrong right now. Critical flags indicate an active condition that poses an immediate risk to deposited capital. They trigger a score penalty and in some cases the vault may be suspended from appearing in default listings.

Critical flags require no interpretation: if you see a red flag, read it carefully before proceeding.

**Examples:**

- The vault is currently paused — deposits and withdrawals are blocked
- An emergency withdrawal has been triggered — a sign of a potential exploit or critical failure
- The underlying stablecoin has depegged by more than 4% from its target price
- TVL has dropped more than 20% in a single day — a potential bank run
- The vault has been losing money for 7 or more consecutive days

### 🟡 Warning

Conditions are elevated or deteriorating. Warning flags don't mean something is broken — they mean you should pay attention. They carry a smaller score penalty than critical flags and are monitored closely by the scoring engine.

**Examples:**

- TVL has dropped more than 10% in a day or 20% over a week
- More than 10% of the vault's TVL is queued for withdrawal
- The vault's yield is more than 25% below what you'd earn from a simple passive alternative
- More than half the vault's yield comes from token incentive emissions
- The average depositor is holding for less than 10 days — elevated mercenary capital signal

### 🔵 Info

A noteworthy characteristic that is relevant to your decision but not a warning. Info flags carry no score penalty. They appear on the vault detail page, not on the vault card summary.

**Examples:**

- The vault launched less than 30 days ago — limited data history
- More than 30% of the vault's yield comes from token incentives (classified as Incentivised Yield)
- The vault uses async withdrawals — there will be a waiting period before funds can be claimed
- APY is slightly below the passive benchmark — not dangerous, but worth noting

---

## How flags interact with the score

Critical flags subtract points directly from the final Yieldo Score. The more severe the flag, the larger the penalty. A vault can accumulate multiple flag penalties simultaneously.

Warning flags carry smaller penalties. Info flags carry no penalty at all — they exist purely to inform.

**A vault can score 80\+ and still carry an Info flag.** This is intentional. An Info flag on a strong vault might mean its yield is partially incentivised, or that it launched recently. Neither of those things makes a well-run vault unsafe — they are just facts worth knowing. The flag system is designed to surface relevant information, not to manufacture concern where none exists.

---

## Flags auto-clear when conditions improve

Flags are not permanent marks against a vault. When the triggering condition resolves — the depeg recovers, the TVL stabilises, the withdrawal queue clears — the flag clears automatically. The scoring engine checks conditions continuously and updates flags in near real-time for critical alerts.

One exception: Emergency Withdraw flags never auto-clear. A vault that has triggered an emergency shutdown requires manual review before it can be reinstated. This is by design — the circumstances that trigger an emergency shutdown warrant human judgement before a vault is considered safe again.

---

## Flag reference summary

| Flag | Severity | Triggered when |
| --- | --- | --- |
| Vault Paused | 🔴 Critical | Vault has halted deposits and withdrawals |
| Emergency Withdraw | 🔴 Critical | Emergency shutdown event detected |
| Asset Depeg (Severe) | 🔴 Critical | Underlying asset \>4% from peg |
| TVL Crash | 🔴 Critical | TVL drops \>20% in 1 day or \>40% in 7 days |
| Sustained Negative APY | 🔴 Critical | Vault losing money for 7\+ consecutive days |
| Capital Flight | 🔴 Critical | Less than 50% of capital from 30 days ago remains |
| Asset Depeg (Moderate) | 🟡 Warning | Underlying asset 2–4% from peg |
| TVL Drop | 🟡 Warning | TVL drops 10–20% in 1 day or 20–40% in 7 days |
| High Incentive Ratio | 🟡 Warning | 25–50% of yield from token emissions |
| Below Benchmark | 🟡 Warning | APY 25–50% of the passive benchmark |
| Elevated Pending Withdrawals | 🟡 Warning | Withdrawal queue is 10–20% of TVL |
| Short Average Holding | 🟡 Warning | Average depositor holds for less than 10 days |
| New Vault | 🔵 Info | Vault is less than 30 days old |
| Incentivised Yield | 🔵 Info | More than 30% of yield from token incentives |
| Async Withdrawals | 🔵 Info | Vault uses delayed withdrawal processing |
| Slightly Below Benchmark | 🔵 Info | APY 50–80% of the passive benchmark |