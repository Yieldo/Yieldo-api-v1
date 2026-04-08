---
title: "Roadmap"
---

# What's Next

_This page covers what is currently in development, what is on the longer-term radar, and how Yieldo's scoring ambitions extend beyond individual vaults. It is relevant to all readers._

---

The current scoring framework covers 75\+ vaults across stablecoin and ETH strategies on Ethereum and Base. It is a working v1.0 — live, scoring, and already surfacing signals that no other tool in the market produces.

It is also deliberately incomplete. DeFi infrastructure moves fast, on-chain data gets richer over time, and the right answer for scoring a vault today is not the same as the right answer in twelve months. This page describes where the framework is going.

---

## Stage 2: In development

### Audit recency and auditor tier

The current framework treats all non-exploited vaults the same from a security verification standpoint. Stage 2 adds a dedicated audit dimension: how recently the vault's smart contracts were audited, and by whom.

Auditor tier will be maintained as a structured registry — Tier 1 includes firms like Trail of Bits, OpenZeppelin, Spearbit, and Consensys Diligence; Tier 2 includes larger commercial audit firms; Tier 3 covers all others. No audit at all results in a score of zero for this sub-metric.

Audit data will be sourced initially from a maintained registry and enriched over time through integrations with DeFi Safety and equivalent platforms.

### Actual withdrawal latency

The current framework captures withdrawal type (instant vs async) but not the actual time depositors wait. Stage 2 adds measured p95 withdrawal latency derived from on-chain event pairs: the time between a withdrawal request and the funds becoming claimable, tracked across all recent withdrawals.

Vaults where the p95 latency exceeds 14 days will trigger a Critical flag. Vaults exceeding 7 days will trigger a Warning. This catches cases where a vault nominally supports withdrawals but processes them so slowly that users are effectively locked in.

### Long-term holder exodus detection

The current Trust dimension measures whether long-term holders exist. Stage 2 adds detection of when they are leaving — a meaningful leading indicator that precedes the kind of TVL collapses that the framework currently only catches after they happen.

### Liquidity exit simulation

For large depositors, the relevant risk is not just whether a vault is safe but whether it is liquid enough to exit without significant slippage. Stage 2 will add estimated exit cost at $10K, $100K, and \$1M tiers, derived from DEX aggregator simulations against the vault's underlying asset.

---

## On the radar

### Curator scoring

The next significant expansion of the framework is moving from vault scoring to curator scoring — an independent assessment of the entity managing the vault strategy, not just the vault itself.

A well-designed vault run by an inexperienced or opaque curator is a different risk profile to the same vault run by a team with a multi-year track record across multiple strategies. Curator scoring will assess track record across all vaults managed, incident history, transparency (published risk frameworks, open communication), team verifiability, and governance structure.

Critically, curator scoring will be kept structurally separate from vault scoring. A curator's score will appear alongside a vault's score, not folded into it — so users can distinguish between a vault that scores well because its design is sound and a vault that scores well because its curator has an outstanding track record.

### Smart money and institutional presence tracking

On-chain data contains strong signals about who is depositing: known DeFi funds, DAOs, governance delegates, and sophisticated individual wallets. When these wallets are present in a vault, it is a meaningful quality signal — these are the actors with the most information and the least tolerance for poorly managed risk.

Smart money tracking requires building and maintaining a labeled address database. This is a significant infrastructure investment, which is why it sits further out on the roadmap, but it will eventually become a component of the Trust dimension.

### Governance signal monitoring

For vaults governed by DAOs or multi-sig structures, governance activity — proposal patterns, quorum participation, timelock compliance — is a meaningful signal of operational health. A vault whose governance has been inactive for twelve months is a different risk profile from one with regular, contested proposals.

### Decentralised curation layer

The longest-horizon item on the roadmap is a decentralised layer that allows the broader DeFi community to participate in vault curation and signal amplification. The details of how this works — whether through token governance, staking, reputation systems, or some combination — are still being designed. The principle is that Yieldo's independence is most durable when it is structurally distributed rather than dependent on a single team's judgment.

---

## What will not change

Across all of these expansions, three things will remain fixed:

**Scoring will always be derived from on-chain data.** External enrichment will continue to improve the user interface, but it will never enter the critical scoring path.

**Vault platforms and curators will never influence scoring methodology.** As the platform grows and commercial relationships deepen, this structural separation becomes more important, not less.

**Missing data will always be a penalty.** As new metrics are added, any vault that cannot be assessed on a new dimension will receive a conservative default, not a neutral one.

The framework will grow. The principles will not.