---
title: "Users"
description: "Investor auth, referral tiers, and role detection"
---

Regular investors (non-partner users) can sign in with a wallet signature to persist a 2-hour session. The user record powers the referral tier system and role detection.

## Get Role

```
GET /v1/users/role/{address}
```

Returns the role of a wallet. Used by the frontend to auto-redirect a connected wallet to the right dashboard (Creator, Wallet Partner, or Investor).

### Response

```json
{ "role": "creator", "handle": "batman" }
```

### Possible Roles

| Role       | Meaning                                                     |
| ---------- | ----------------------------------------------------------- |
| `creator`  | Address is registered as a Creator (also includes legacy `kol`) |
| `wallet`   | Address is registered as a Wallet Partner                    |
| `user`     | Default — regular investor                                  |

---

## Referral Stats & Tier

```
GET /v1/users/referrals/{address}
```

Returns referral activity for a wallet's own referral link — including tier, depositing referral count, and Yieldo Points. Used by the Referrals page to display progress toward Creator invite unlock.

### How Referrals Are Counted

A "depositing referral" is a **distinct** `user_address` from the transactions collection whose `referrer` field matches the queried address and whose deposit is `completed`, `submitted`, or `pending`. Self-referrals are excluded.

### Response

```json
{
  "address": "0xab3d...",
  "clicks": 0,
  "signups": 0,
  "depositing": 7,
  "points": 840,
  "tier": 1,
  "tier_label": "Active Referrer",
  "tier1_threshold": 3,
  "tier2_threshold": 10,
  "creator_unlocked": false
}
```

### Fields

| Field              | Type         | Description                                                            |
| ------------------ | ------------ | ---------------------------------------------------------------------- |
| `clicks`           | int          | Reserved — click-tracking not wired yet (returns 0)                    |
| `signups`          | int          | Reserved — returns 0                                                   |
| `depositing`       | int          | Unique depositing referrals                                            |
| `points`           | int          | Yieldo Points earned (120 × depositing — display as "coming soon")     |
| `tier`             | int          | `0` = no tier, `1` = Active Referrer, `2` = Top Referrer               |
| `tier_label`       | string/null  | Human-readable label                                                   |
| `tier1_threshold`  | int          | `3` — unlocks Active Referrer                                          |
| `tier2_threshold`  | int          | `10` — unlocks Top Referrer + Creator invite                           |
| `creator_unlocked` | bool         | `true` when `depositing >= tier2_threshold` (user can register without code) |

---

## Get Nonce

```
POST /v1/users/nonce
```

Generate a nonce for login signature.

### Request

```json
{ "address": "0xYourWalletAddress" }
```

### Response

```json
{
  "nonce": "a1b2c3...",
  "message": "Sign this message to login to Yieldo.\n\nAddress: 0x...\nNonce: a1b2c3..."
}
```

---

## Login

```
POST /v1/users/login
```

Auto-registers a user on first login. Subsequent logins just refresh the session.

### Request

```json
{ "address": "0x...", "signature": "0x..." }
```

### Response

```json
{
  "session_token": "...",
  "expires_at": "2026-04-14T14:00:00+00:00",
  "user": {
    "address": "0x...",
    "created_at": "2026-04-14T12:00:00+00:00",
    "status": "active"
  }
}
```

Sessions expire after 2 hours.

---

## Get Current User

```
GET /v1/users/me
```

Requires `Authorization: Bearer <session_token>` header.

### Response

```json
{
  "address": "0x...",
  "status": "active",
  "created_at": "2026-04-14T12:00:00+00:00"
}
```

---

## Logout

```
POST /v1/users/logout
```

Invalidates all sessions for the wallet (reads the session from the `Authorization` header).
