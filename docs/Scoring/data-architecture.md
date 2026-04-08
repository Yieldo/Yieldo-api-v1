---
title: "Data Architecture"
---

# Technical Deep-Dive: Data Architecture

_This page covers how the scoring engine gets its data — sources, reliability tiers, update frequencies, and failure handling. It is written for technical readers evaluating the independence and robustness of the scoring infrastructure. For the scoring model itself, see_ [_Technical Deep-Dive: Scoring Model_](page-6-scoring-model.md)_._

---

## The three-layer data model

The scoring engine separates data into three layers with different reliability guarantees and different roles in score computation.

**Layer 1 — On-Chain (trustless, universal)** The primary data source. Derived directly from vault contracts, deposit and withdrawal events, price oracles, and governance contracts on Ethereum, Base, and Arbitrum. Available as long as the blockchain runs. No API dependency. Everything that affects the Yieldo Score must be derivable from Layer 1 alone.

**Layer 2 — Computed (Yieldo engine)** Metrics calculated by the Yieldo scoring engine from indexed Layer 1 data. Fully deterministic. Rolling APY, Sharpe ratio, drawdown metrics, retention rates, HODL ratio, all Trust metrics, all flags, and the final score are computed here.

**Layer 3 — Enrichment (optional, best-effort)** External data sources used to improve the user interface but never in the critical scoring path. Curator names and bios, vault strategy descriptions, external risk ratings (Bluechip, Credora, DeFi Safety). Cached daily. If enrichment fails, the score is unaffected and the UI degrades gracefully — "Unknown curator" instead of a named risk manager.

**Only two metrics touch Layer 3:** Yield Composition (organic vs incentivised split, sourced from Morpho API) and External Rating Count (number of independent risk ratings). Both have defined fallback values if unavailable — Yield Composition defaults to "Unknown" and scores to 50; External Ratings default to 0 (no bonus). Neither blocks score computation.

---

## Layer 1: On-chain data sources

| Source | Method | Metrics Derived | Cadence |
| --- | --- | --- | --- |
| ERC-4626 vault contract | `totalAssets()` | TVL, TVL change | Hourly snapshot |
| ERC-4626 vault contract | `convertToAssets(1e18)` or NAV ratio | Realized APY, Sharpe, drawdown, all performance metrics | Hourly snapshot |
| ERC-4626 events | `Deposit(sender, owner, assets, shares)` | Net flows, depositor count, all Trust metrics | Real-time |
| ERC-4626 events | `Withdraw(sender, receiver, owner, assets, shares)` | Net flows, holding duration, Trust metrics | Real-time |
| Vault admin events | `Paused()`, `EmergencyWithdraw`, `OwnershipTransferred` | Pause flags, emergency flags, incident count | Real-time |
| Price feeds | CoinGecko API (Chainlink planned for Stage 2) | Asset depeg detection, USD denomination | Every 5 minutes |
| DeFiLlama /pools API | Aave V3 supply rates, Lido stETH rate | Performance benchmark (APY vs Benchmark metric) | Every 6 hours |
| Vault token | `balanceOf(address)` \+ Transfer events | Depositor concentration (top-5 share), unique depositors | Daily batch |
| Timelock contract | `timelock()` read | Access Control / Timelock metric | Every 48 hours |

**ERC-4626 as universal interface.** The ERC-4626 tokenized vault standard is the common denominator across Morpho, Yearn v3, Lagoon, Hyperbeat, Upshift, and most modern vault platforms. One indexer architecture covers all compliant vaults without platform-specific code. Vaults that do not comply with ERC-4626 require an adapter and are a Stage 2 consideration.

---

## Metric update frequencies

| Tier | Frequency | Metrics |
| --- | --- | --- |
| Critical alerts | Every 5 minutes | TVL, APY, depeg detection, pause state, pending withdrawals, all flag triggers |
| Performance | Every 5 minutes | Sharpe, Win Rate, Drawdown, Worst Week, Alpha Consistency, Yield Composition |
| Benchmarks | Every 6 hours | Aave supply rates, ETH staking rate — fetched from DeFiLlama /pools API |
| Depositor analysis | Every 12 hours | Retention rates, HODL ratio, holding durations, Quick Exit Rate, Net Flow Direction, concentration |
| Security | Every 48 hours | Incident history, timelock status, pause event log |

---

## Vault discovery

The indexer needs to know which contracts to watch. Three discovery methods run in priority order:

**Factory indexing (primary).** The indexer monitors vault factory contracts that emit events when new vaults are created. Morpho's `MetaMorphoFactory.CreateMetaMorpho`, Yearn's `VaultFactory.NewVault`, and equivalent factory events for other platforms are indexed continuously. New vault detected → added to registry → indexing begins within one block. Fully automatic with no manual intervention.

**Manual registration (fallback).** For vaults deployed outside a monitored factory, operators can submit a vault address directly. Subject to a brief verification step before indexing begins.

**Periodic factory scan.** A scheduled scan of known factory addresses catches any vaults that may have been missed by the real-time listener, typically due to brief indexer downtime.

---

## Protocol-specific data sources

Some vault platforms expose APIs that provide more accurate data than on-chain calculation alone — pre-computed APY figures, curator metadata, depositor balance data. Where a platform API improves accuracy over a raw on-chain calculation, we use it as an override. Where it is unavailable, scoring falls back to on-chain data without interruption.

This applies to all current vault partners including Morpho, Midas, Lagoon, Hyperbeat, and Upshift. Platform APIs are always Layer 3 — enrichment only. They improve the accuracy and presentation of data but are never in the critical scoring path. If a platform API goes down, the score continues to compute from on-chain data.

---

## Failure modes and graceful degradation

The scoring engine is designed to keep producing scores even when individual data sources fail.

| Failure | Impact | Response |
| --- | --- | --- |
| RPC node down | Snapshots stall; no new on-chain data | Failover to backup RPC. Last known scores served until data resumes. Score not affected. |
| Price feed stale | Depeg detection may delay | Backup oracle used. Affected vaults flagged with stale price warning. Minor score impact. |
| Morpho API down | Curator metadata unavailable | Cached enrichment served (Redis TTL). UI shows "data may be outdated." Score unaffected. |
| Aave benchmark unavailable | APY vs Benchmark metric unavailable | Last known rate used if \< 24 hours stale. If \> 24 hours, benchmark sub-score defaults to 50. Minor impact — five other performance metrics unaffected. |
| Scoring engine crash | New scores not computed | Restart job. API continues serving last valid scores with timestamp notice. |

---

## Adding a new vault platform

The scoring engine is protocol-agnostic by design. Onboarding a new ERC-4626-compliant platform typically takes less than a day of engineering work.

1. Confirm ERC-4626 compliance — call `totalAssets()`, `convertToAssets()`, verify Deposit/Withdraw events (\< 1 hour)
2. Identify the vault factory contract and its creation event signature (1–2 hours)
3. Register the factory in the indexer config — one configuration change, Ponder auto-discovers new vaults (30 minutes)
4. Backfill existing vaults into the registry from factory event history (1–2 hours)
5. Verify scoring output on 2–3 vaults from the new platform against known data (2–4 hours)
6. Optionally build an enrichment integration for curator metadata — useful for the UI, not required for scoring (4–8 hours)

Platforms that do not implement ERC-4626 require a custom adapter. This is a Stage 2 consideration and is handled on a case-by-case basis.