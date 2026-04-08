---
title: "Design Principles"
---

# Design Principles

_This page explains the principles that govern how the Yieldo Scoring Framework is built and maintained. It is relevant to all readers — wallet users who want to understand our approach, and technical readers who want to know what we optimise for before diving into the model._

---

These are not aspirational values. They are engineering constraints. Every decision in the scoring model — what to measure, how to weight it, when to penalise, when to stay silent — is tested against these five principles before it is adopted.

---

## 1. Platform, not Advisor

Yieldo curates and scores. It never recommends.

The score is a quality signal. What you do with it is entirely your decision. Wallets set their own minimum score thresholds. Users set their own risk tolerance. Yieldo provides the most accurate, independent signal it can — and then gets out of the way.

This matters because the alternative — a system that tells users what to do — requires the system to know things it cannot know: your financial situation, your time horizon, your risk capacity. We don't know those things. We know on-chain data. We score on-chain data.

---

## 2. Transparency by Default

Every score shows its breakdown. There are no black boxes.

If a vault scores 74, you can see exactly how much of that came from Capital, Performance, Risk, and Trust. If a flag is active, you can see what triggered it. If a metric is unavailable because the vault is too new, that gap is shown explicitly rather than filled with an assumption.

We publish the methodology behind the score — the dimensions we measure, the data sources we use, the principles we apply — so that any DeFi user with the time and knowledge can verify our reasoning.

What we do not publish is the exact scoring formulas and internal weights. This is the one deliberate boundary in our transparency. The reason is practical, not secretive: publishing precise formulas would allow vault operators to optimise for the score rather than for the underlying quality the score is trying to measure. The methodology is open. The implementation detail that would enable gaming is not.

---

## 3. Three Signal Layers

The scoring engine produces three distinct outputs because different users need information in different forms.

**Metrics** are raw numbers — TVL, APY, holding durations, depositor counts. They are shown on vault cards and detail pages for users who want to compare and decide for themselves.

**Flags** are threshold-based alerts that fire when something specific happens — a TVL crash, a depeg, sustained negative yield. They exist because some conditions require immediate visibility regardless of where the overall score sits.

**The Yieldo Score** is the composite signal that combines everything. It is optimised for a single use case: sorting and filtering vaults by overall quality so that the safest, most reliable vaults surface first.

Each layer serves a different cognitive mode. Together they give users the information they need at whatever depth they want to engage.

---

## 4. Fail Safe

Missing data is treated as a penalty, not as a neutral assumption.

If the scoring engine cannot calculate a metric — because the vault is too new, because a data source is temporarily unavailable, because the vault's contract doesn't expose the required information — the score decreases. It never increases on the assumption that the missing data would have been good.

This is the conservative choice by design. A vault that cannot be fully assessed should not benefit from the gap. Users deserve to know when data is missing, and the score should reflect the genuine uncertainty that missing data creates.

---

## 5. On-Chain First

Every metric that affects the Yieldo Score is derived from on-chain data — vault contracts, deposit and withdrawal events, price oracles, governance contracts.

Platform APIs and external data sources are used for enrichment: curator names, strategy descriptions, external risk ratings. This enrichment improves the user interface but it is never in the critical scoring path. If Morpho's API goes down, scores still compute. If a curator's website is unreachable, the score is unaffected.

This is the only architecture that produces a score that is genuinely independent. A scoring engine that depends on a platform's own API to calculate scores is, in a meaningful sense, letting the platform influence its own assessment. On-chain data cannot be selectively withheld or shaped by the entities being scored.

---

## On independence

Yieldo does not accept listing fees. Vault platforms and curators cannot pay to appear on the platform or to improve their scores. The only input curators have into the scoring model is the quality of the vaults they run.

This independence is structural, not just stated. Because scoring is derived from on-chain data, and because curators have no access to scoring methodology, there is no mechanism by which commercial relationships between Yieldo and its vault partners can influence what the scoring engine produces.

We believe this independence is the entire value of the platform. A scoring system that can be influenced by the entities it scores is not a scoring system — it is marketing.