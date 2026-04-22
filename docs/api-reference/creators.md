---
title: "Creators"
description: "Creator (KOL) registration, invite codes, and public profiles"
---

Creator accounts (formerly "KOL") are invite-only, wallet-authenticated profiles that route revenue share from vault deposits. Every Creator has a public page at `yieldo.xyz/u/<handle>` and an on-chain attribution identity.

<Note>
All endpoints are available under both `/v1/creators/*` (canonical) and `/v1/kols/*` (legacy alias). Both paths hit identical handlers. New integrations should use `/v1/creators/*`.
</Note>

## Invite-only Registration

A wallet can register as a Creator only if it holds **either**:

1. A valid, unused invite code (dropped on X/Twitter every 2-3 weeks), **or**
2. A **Top Referrer** tier (10+ depositing referrals — see [Referrals](#referrals)).

---

## Get Public Profile

```
GET /v1/creators/public/{handle}
```

Returns the public-facing Creator profile. No auth required.

### Response

```json
{
  "handle": "batman",
  "name": "Batman",
  "bio": "DeFi yield expert",
  "twitter": "batmanDeFi",
  "enrolled_vaults": ["1:0xbeef01735c132ada46aa9aa4c54623caa92a64cb"],
  "created_at": "2026-04-14T12:00:00+00:00",
  "founding_creator": true
}
```

| Field              | Type     | Description                                                  |
| ------------------ | -------- | ------------------------------------------------------------ |
| `handle`           | string   | Creator's unique handle (lowercase, 3-32 chars)              |
| `name`             | string   | Display name                                                 |
| `bio`              | string   | Short bio                                                    |
| `twitter`          | string   | Twitter/X handle (without `@`)                               |
| `enrolled_vaults`  | string[] | Vault IDs the Creator has curated                            |
| `created_at`       | string   | ISO-8601 registration timestamp                              |
| `founding_creator` | boolean  | `true` for early-access members — displays a special badge   |

---

## Resolve Handle

```
GET /v1/creators/resolve/{handle}
```

Resolves a handle to the Creator's referrer address (for attribution). Used by the frontend's `?ref=handle` flow.

### Response

```json
{
  "handle": "batman",
  "name": "Batman",
  "address": "0xab3d...",
  "fee_enabled": true
}
```

---

## Verify Invite Code

```
POST /v1/creators/invite/verify
```

Checks whether an invite code is valid and unused. Does **not** consume the code.

### Request

```json
{ "code": "MORPHO" }
```

### Response

```json
{ "valid": true, "code": "MORPHO" }
```

### Errors

| Status | Description                         |
| ------ | ----------------------------------- |
| 400    | Code required                       |
| 404    | Invalid or already-used code        |

---

## Apply for Creator Access

```
POST /v1/creators/apply
```

Submits a manual application for Creator access when the user doesn't have an invite code. Applications are reviewed weekly.

### Request

```json
{
  "address": "0xYourWalletAddress",
  "twitter": "yourHandle",
  "audience": "5000",
  "description": "I write DeFi threads and newsletters..."
}
```

### Response

```json
{ "ok": true, "application_id": "...", "status": "pending" }
```

If an application already exists for the address, the existing status is returned.

---

## Nonce (for signing)

```
POST /v1/creators/nonce
```

Generates a nonce for wallet signature. Returns the message to sign. The message indicates whether the wallet will be registering or logging in.

### Request

```json
{ "address": "0xYourWalletAddress" }
```

### Response

```json
{
  "nonce": "a1b2c3d4...",
  "message": "Sign this message to register as a Yieldo Creator.\n\nAddress: 0x...\nNonce: a1b2c3d4..."
}
```

---

## Register Creator

```
POST /v1/creators/register
```

Register a new Creator. Requires an invite code unless the wallet has 10+ depositing referrals.

### Request

```json
{
  "address": "0xYourWalletAddress",
  "signature": "0x...",
  "handle": "yourhandle",
  "name": "Your Name",
  "bio": "Optional short bio",
  "twitter": "yourTwitter",
  "invite_code": "MORPHO"
}
```

### Response

```json
{
  "address": "0x...",
  "handle": "yourhandle",
  "name": "Your Name",
  "created_at": "2026-04-14T12:00:00+00:00"
}
```

All successful registrations are flagged as Founding Creators.

### Errors

| Status | Description                                                        |
| ------ | ------------------------------------------------------------------ |
| 400    | Invalid invite code, bad handle format, or no pending nonce        |
| 401    | Invalid signature                                                  |
| 403    | No invite code AND insufficient depositing referrals               |
| 409    | Handle already taken, or address already registered                |

---

## Login

```
POST /v1/creators/login
```

Login an existing Creator. Returns a session token valid for 24 hours.

### Request

```json
{ "address": "0x...", "signature": "0x..." }
```

### Response

```json
{
  "session_token": "...",
  "expires_at": "2026-04-15T12:00:00+00:00",
  "creator": { "address": "0x...", "handle": "yourhandle", "name": "Your Name" }
}
```

Pass the `session_token` as `Authorization: Bearer <token>` on authenticated endpoints.

---

## Authenticated Endpoints

| Endpoint                           | Description                              |
| ---------------------------------- | ---------------------------------------- |
| `GET  /v1/creators/me`             | Current Creator profile + settings       |
| `PUT  /v1/creators/settings`       | Update profile (name, bio, twitter, etc.)|
| `GET  /v1/creators/vaults`         | Enrolled vaults                          |
| `PUT  /v1/creators/vaults`         | Update enrolled vault IDs                |
| `GET  /v1/creators/dashboard`      | Dashboard stats (referrals, volume, etc.)|
| `GET  /v1/creators/referrals`      | List referred users                      |
| `POST /v1/creators/logout`         | Invalidate current session               |
