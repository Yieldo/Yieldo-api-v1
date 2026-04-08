# The Four Dimensions

_This page explains what each dimension measures in plain language. If you already understand the dimensions and want the scoring formulas, weights, and technical logic, skip to the_ [_Technical Deep-Dive_](page-6-scoring-model.md)_._

The Yieldo Score is built from four dimensions, each measuring a different aspect of vault quality. Every dimension contributes to the final score, but not equally — because not all risks are equal.

| Dimension | Weight | Core question |
|-----------|--------|---------------|
| 🏦 Capital | 20% | Is this vault large enough and stable enough to be trusted? |
| 📈 Performance | 20% | Is the yield real, consistent, and competitive? |
| 🛡️ Risk | 35% | Is your capital protected from exploits, depegs, and emergencies? |
| 🤝 Trust | 25% | Are depositors staying, or farming and leaving? |


**Why Risk carries the most weight.** For yield vaults — especially stablecoin vaults — the primary job is not to maximise return. It is to not lose money. A vault that earns 8% APY and then suffers an exploit is worse than a vault that earns 5% and never has an incident. Risk is weighted heaviest because that reflects how depositors actually experience outcomes.


---

## 🏦 Capital

**What it measures:** The size, stability, and growth trajectory of the vault.

Capital looks at how much money is in the vault, whether that amount is growing or shrinking, how many unique depositors are participating, and whether there is a significant queue of pending withdrawals waiting to exit.

A vault with $50M in TVL, steady inflows, and thousands of depositors signals a very different story than a vault with $200K, two depositors, and a large withdrawal queue.

**What causes a low Capital score:**
- Very low TVL — the vault hasn't attracted meaningful capital
- A large or growing pending withdrawal queue — depositors are trying to leave
- Very few unique depositors — one or two large wallets dominate, creating exit risk if they leave
- Significant net outflows over the past 7–30 days

---

## 📈 Performance

**What it measures:** Whether the vault is generating real, consistent yield that justifies the risk of using it.

Performance looks beyond the headline APY. It evaluates whether the yield comes from genuine revenue (lending fees, trading activity) or from token incentive emissions that will eventually run out. It measures how consistent returns have been over time, how the vault compares to a simple passive alternative like lending on Aave, and whether the vault has experienced any significant drawdowns.

A vault yielding 12% APY from token incentives that are scheduled to end in 60 days is a fundamentally different proposition to one yielding 6% from stable organic revenue.

**What causes a low Performance score:**
- Yield that is mostly or entirely made up of token incentive emissions
- APY that is significantly below what you could earn from a simple passive alternative (e.g. lending the same asset on Aave)
- A history of drawdowns — periods where the vault's value declined
- Inconsistent returns, swinging between weeks of strong performance and weeks of negative yield

---

## 🛡️ Risk

**What it measures:** How protected your capital is from the things that can destroy it — exploits, depegs, governance attacks, and emergency shutdowns.

Risk is the most technically demanding dimension to calculate. It looks at whether the vault has ever been paused or experienced an emergency exit, whether the underlying stablecoin has ever depegged from its intended value, how concentrated depositor balances are (a vault where 80% of TVL sits in one wallet is fragile), and how much time is built into the vault's upgrade process to prevent sudden changes.

The goal is to answer one specific question: *is this vault safe right now?* Not whether it was designed well — whether it is currently safe.

**What causes a low Risk score:**
- Any history of exploits, hacks, or emergency shutdowns — even resolved ones
- The vault's underlying asset depegging from its target price
- Extremely high depositor concentration — one or two wallets holding most of the TVL
- The vault currently being paused (this triggers a critical red flag immediately)
- No timelock on vault upgrades — meaning changes can be made instantly with no warning period


**🔴 Critical flags always override the score.** If a vault is currently paused, experiencing an active depeg, or has triggered an emergency withdrawal event, it will display a critical red flag regardless of its underlying score. A vault in active crisis is not suitable for new deposits.


---

## 🤝 Trust

**What it measures:** Whether real depositors are staying — or whether they deposit briefly, collect yield, and leave.

Trust is Yieldo's most distinctive dimension. It measures capital and depositor behaviour over time: how long people typically hold their deposits, what percentage of capital from 30 days ago is still in the vault today, how much capital is flowing in versus out, and what share of deposits come from long-term holders who have been in the vault for 60 days or more.

A vault where depositors stay for months is a fundamentally safer environment than one where most deposits exit within a week. Mercenary capital — short-term farmers chasing incentives — creates fragile vaults that are vulnerable to sudden TVL collapses when incentives change.

**What causes a low Trust score:**
- Most depositors leaving within 7 days of depositing — a classic farm-and-dump pattern
- Low capital retention: a significant share of capital from last month has already left
- Net outflows over the past 30 days — more capital leaving than entering
- Very short average holding periods across all depositors
- Capital dominated by recent depositors with no long-term holder base


**Trust and Risk together tell the most important story.** A vault with a high Risk score but low Trust score often means the vault is well-designed but depositors don't believe in it enough to stay. A vault with high Trust but moderate Risk means depositors are sticky — but it may be worth understanding why the Risk score is lower before committing significant capital.

