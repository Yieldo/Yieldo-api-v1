---
title: "Hashlock Smart Contract Audit"
description: "May 2026 audit of Yieldo's attribution and routing layer by Hashlock. Final rating: Secure."
---

Yieldo's on-chain attribution and routing layer was audited by [Hashlock](https://hashlock.com) in May 2026. The audit covered the Solidity contracts that handle deposit routing, vault dispatch, and on-chain attribution — i.e. every contract a user's funds touch when depositing through Yieldo.

## Report

- **Auditor:** Hashlock
- **Audit name:** Yieldo Smart Contract Audit Report
- **Date:** May 2026
- **Language:** Solidity
- **Final rating:** **Secure**
- **Full report:** [hashlock.com/audits/yieldo](https://hashlock.com/audits/yieldo)

## Scope

The audit covered Yieldo's **attribution and routing layer** — the contracts that sit between the user and the partner vault on every deposit:

- `DepositRouter.sol` — non-custodial pass-through router (V3.2.0 on all chains, see [Deposit Router Contracts](/guides/deposit-router-contracts))
- `Proxy.sol` — upgradeable proxy that fronts the router
- `adapters/` — per-protocol dispatch logic (ERC-4626, Midas issuance, Veda teller, Lido queue, custom)
- `interfaces/` — external vault interfaces consumed by the adapters

## Why the attack surface is narrow

The router's design deliberately minimizes the surface an auditor has to reason about, and the rating reflects that:

- **Non-custodial.** Funds are pulled from `msg.sender` and delivered to the vault inside the same transaction. The router holds no balances between transactions.
- **No fee extraction from deposits.** 100% of user tokens reach the vault — there is no protocol-side fee bps, no skim, no withhold.
- **No discretionary control over user assets.** The router has no admin function that can move user funds, pause withdrawals, or sweep balances. The only privileged surface is the adapter dispatch table.
- **Atomic settlement.** Either the vault mints shares to the user in the same tx, or the whole call reverts — there is no intermediate state where funds can be stranded in the router.

This is the architectural reason a "Secure" rating is achievable: there is very little a malicious or buggy router code path could do, because the router is not a custodian.

## How this surfaces in the Yieldo score

The Hashlock audit feeds the **Trust** dimension of the [Yieldo Score](/Scoring/four-dimensions). Audited contracts contribute positively to a vault's Trust sub-scores; in Stage 2 of the [Scoring Roadmap](/Scoring/roadmap), auditor tier and audit recency become first-class signals with Hashlock recognized as a maintained registry entry.

## Re-audits and future changes

The router is upgradeable behind `Proxy.sol`. Any future router upgrade that materially changes the attribution or routing logic will be re-submitted to Hashlock (or an equivalent tier auditor) before the proxy `upgradeTo` call lands on mainnet. The current audited build is V3.2.0 — see the [Deposit Router Contracts](/guides/deposit-router-contracts) page for upgrade history and current proxy addresses per chain.
