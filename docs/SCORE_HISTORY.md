# Score History API — Frontend Integration Guide

The score-history feature exposes hourly snapshots of every vault's
composite score, 4 dimensions, and tracked sub-metrics. Plus anomaly
detection (TVL crashes, score drops, hacks) and biggest-mover queries
for socials content.

Backend write side: `indexer-v1/src/score_history.py` writes one row per
`(vault_id, hour)` to `score_snapshots`, plus detected anomalies to
`score_anomalies`.

Backend read side: `Yieldo-api-v1/app/routes/scores.py` exposes the
endpoints below.

## TL;DR — what to build

| Feature                    | Endpoint                              | Chart type             |
| -------------------------- | ------------------------------------- | ---------------------- |
| "Score evolution" tab      | `/v1/scores/history/{vault_id}`       | Multi-line area        |
| Single-metric mini chart   | `/v1/scores/timeseries/{vid}/{metric}`| Sparkline              |
| Top movers (socials)       | `/v1/scores/movers`                   | Card list              |
| Live alerts feed           | `/v1/scores/anomalies`                | Stream                 |
| Vault leaderboard          | `/v1/scores/leaderboard`              | Ranked table           |
| "Compare vaults"           | `/v1/scores/compare?vault_ids=a,b,c`  | Multi-line overlay     |

Base URL: `https://api.yieldo.xyz` (prod) or `http://localhost:8000` (dev).

---

## Endpoints

### `GET /v1/scores/history/{vault_id}`

Full chart history for a vault. Returns hourly or daily resolution.

**Query params**
- `days` — int, 1–365 (default 30)
- `interval` — `"hour"` or `"day"` (default `"hour"`)

**Response**
```json
{
  "vault_id": "1:0xbeef01735c132ada46aa9aa4c54623caa92a64cb",
  "days": 30,
  "interval": "hour",
  "count": 720,
  "history": [
    {
      "hour": "2026-03-29T14",
      "ts": "2026-03-29T14:23:01.000000",
      "name": "Steakhouse USDC",
      "source": "Morpho",
      "chain_id": 1,
      "asset": "usdc",
      "yieldo_score": 48.41,
      "capital_score": 59.5,
      "performance_score": 65.0,
      "risk_score": 82.0,
      "trust_score": 51.25,
      "confidence_multiplier": 1.0,
      "flag_penalties": 18,
      "external_rating_bonus": 0,
      "metrics": {
        "C01_USD": 120320458.68,
        "net_apy": 0.03568,
        "P01_7d": 0.0399,
        "P03_7d": 0.766,
        "P04_30d": 0.000539,
        "P08_30d": 0.0,
        "C02_1d": -1.24,
        "C02_7d": -29.23,
        "C02_30d": -43.97,
        "T01_30d": 56.02,
        "T04": 180.19,
        "C07": 500,
        "R09_top1": 0.277,
        "R09_top5": 0.498
      }
    }
  ]
}
```

### `GET /v1/scores/timeseries/{vault_id}/{metric}`

Single-metric series (e.g. just TVL or just APY) — perfect for sparklines.

**Allowed metric values** (case-sensitive): `yieldo_score`, `capital_score`,
`performance_score`, `risk_score`, `trust_score`, `C01_USD`, `net_apy`,
`all_time_apy`, `fee`, `C07`, `P01_1d`, `P01_7d`, `P01_30d`, `P03_7d`,
`P04_30d`, `P04_365d`, `P08_30d`, `P08_90d`, `P08_365d`, `C02_1d`, `C02_7d`,
`C02_30d`, `T01_30d`, `T01_365d`, `T04`, `T07`, `T11`, `R09_top1`, `R09_top5`,
`P05` (Sharpe), `P13` (win rate), `benchmark_apy`.

**Response**
```json
{
  "vault_id": "1:0xbeef01735c132ada46aa9aa4c54623caa92a64cb",
  "metric": "C01_USD",
  "days": 30,
  "count": 720,
  "points": [
    {"x": "2026-03-29T14:00:00", "y": 210652301.31},
    {"x": "2026-03-29T15:00:00", "y": 211003040.50},
    ...
  ]
}
```

### `GET /v1/scores/movers`

Biggest score changes — perfect for socials content ("Top vault that gained
+12 yieldo_score in 24h"). Sorted by signed delta when `direction=up|down`,
or by absolute delta when `direction=both`.

**Query params**
- `window` — `1h` / `6h` / `24h` / `7d` / `30d` (default `24h`)
- `direction` — `up` / `down` / `both` (default `both`)
- `dimension` — `yieldo_score` / `capital_score` / `performance_score` / `risk_score` / `trust_score` (default `yieldo_score`)
- `limit` — int, 1–100 (default 10)

**Response**
```json
{
  "window": "24h",
  "dimension": "yieldo_score",
  "direction": "down",
  "count": 5,
  "movers": [
    {
      "vault_id": "1:0x604117f0c94561231060f56cd2ddd16245d434c5",
      "name": "AavEthena Loop Mainnet",
      "source": "IPOR",
      "chain_id": 1,
      "asset": "usde",
      "before": 35.2,
      "after": 12.6,
      "before_ts": "2026-04-26T15:00:00",
      "after_ts": "2026-04-27T15:00:00",
      "delta": -22.6,
      "tvl_before": 1450000,
      "tvl_after": 1447000
    }
  ]
}
```

### `GET /v1/scores/anomalies`

Detected anomalies (score crashes, TVL flashes, holder exoduses, etc.).

**Query params**
- `window` — same as `/movers`
- `severity` — `critical` / `warning` / `info` (optional)
- `vault_id` — filter to a single vault (optional)
- `limit` — int, 1–500 (default 50)

**Response**
```json
{
  "window": "24h",
  "severity": "critical",
  "count": 2,
  "anomalies": [
    {
      "vault_id": "1:0x...",
      "name": "Some Vault",
      "ts": "2026-04-27T08:15:23",
      "type": "TVL_FLASH",
      "severity": "critical",
      "message": "TVL dropped 47.2% in 1h ($83M → $44M)",
      "detail": {
        "before": 83000000,
        "after": 43800000,
        "pct": -0.472
      }
    },
    {
      "vault_id": "1:0xc4c00d8b...",
      "name": "IPOR wstETH Base",
      "ts": "2026-04-27T07:00:00",
      "type": "APY_FLIP",
      "severity": "critical",
      "message": "APY sign flipped: +0.74% → -4.76%",
      "detail": {"before": 0.0074, "after": -0.0476}
    }
  ]
}
```

**Anomaly types:**

| Type                   | Severity        | Trigger                                                     |
| ---------------------- | --------------- | ----------------------------------------------------------- |
| `SCORE_CRASH`          | critical / warn | yieldo_score dropped ≥10 (crit) / ≥5 (warn) in 1h           |
| `DIMENSION_DROP`       | critical        | A dimension dropped ≥15 in 1h                               |
| `TVL_FLASH`            | critical        | TVL moved ≥30% in 1h                                        |
| `TVL_DRAIN_24H`        | critical        | TVL dropped ≥30% in 24h                                     |
| `APY_SPIKE`            | warning         | APY moved ≥5pp in 1h                                        |
| `APY_FLIP`             | critical        | APY changed sign                                            |
| `HOLDER_EXODUS`        | critical        | Holder count dropped ≥30% in 24h                            |
| `SOURCE_REGRESSION`    | critical        | net_apy.source fell back to `vaultsfyi` (the IPOR-bug class)|
| `PAUSE_DETECTED`       | critical        | Vault entered paused state                                  |
| `FLAG_ESCALATION`      | critical        | New critical flag (F01–F32) triggered                       |
| `METRIC_NULLED`        | critical        | A previously-set critical metric is now null                |

### `GET /v1/scores/leaderboard`

Current ranking across all vaults — latest snapshot per vault.

**Query params**
- `dimension` — same as `/movers` (default `yieldo_score`)
- `limit` — 1–200 (default 20)
- `asset` — filter by asset (`usdc`, `weth`, ...)
- `chain_id` — filter by chain
- `source` — filter by protocol (`Morpho`, `IPOR`, `Lido`, ...)

**Response**
```json
{
  "dimension": "yieldo_score",
  "filters": {"asset": "usdc", "chain_id": null, "source": null},
  "count": 20,
  "leaderboard": [
    {
      "rank": 1,
      "vault_id": "8453:0xbeef010f9cb27031ad51e3333f9af9c6b1228183",
      "name": "Steakhouse USDC",
      "source": "Morpho",
      "chain_id": 8453,
      "asset": "usdc",
      "score": 84.79,
      "yieldo": 84.79,
      "tvl": 293028728.71,
      "apy": 0.03056,
      "ts": "2026-04-27T10:54:58"
    }
  ]
}
```

### `GET /v1/scores/compare`

Multi-vault overlay chart — same dimension, same time window, multiple vaults.

**Query params**
- `vault_ids` — comma-separated, 2–5 ids
- `days` — 1–365 (default 30)
- `dimension` — same as `/movers`

**Response**
```json
{
  "dimension": "yieldo_score",
  "days": 30,
  "series": [
    {
      "vault_id": "1:0xabc...",
      "name": "Steakhouse USDC",
      "points": [{"x": "2026-03-29T00", "y": 48.4}, ...]
    },
    {
      "vault_id": "1:0xdef...",
      "name": "Gauntlet USDC Prime",
      "points": [{"x": "2026-03-29T00", "y": 51.2}, ...]
    }
  ]
}
```

---

## Frontend integration (React + Recharts example)

### 1. Install Recharts (or your chart lib of choice)

```bash
npm install recharts swr
```

### 2. Score evolution chart

```tsx
import { LineChart, Line, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer } from "recharts"
import useSWR from "swr"

const fetcher = (url: string) => fetch(url).then(r => r.json())

export function ScoreEvolution({ vaultId }: { vaultId: string }) {
  const { data, error } = useSWR(
    `/v1/scores/history/${encodeURIComponent(vaultId)}?days=30&interval=day`,
    fetcher,
    { refreshInterval: 60_000 }  // refresh once per minute
  )

  if (error) return <div>Failed to load</div>
  if (!data) return <div>Loading…</div>

  const chartData = data.history.map((r: any) => ({
    date: r.hour.slice(0, 10),
    "Total":       r.yieldo_score,
    "Capital":     r.capital_score,
    "Performance": r.performance_score,
    "Risk":        r.risk_score,
    "Trust":       r.trust_score,
  }))

  return (
    <ResponsiveContainer width="100%" height={300}>
      <LineChart data={chartData}>
        <XAxis dataKey="date" />
        <YAxis domain={[0, 100]} />
        <Tooltip />
        <Legend />
        <Line type="monotone" dataKey="Total"       stroke="#0f172a" strokeWidth={3} />
        <Line type="monotone" dataKey="Capital"     stroke="#3b82f6" />
        <Line type="monotone" dataKey="Performance" stroke="#10b981" />
        <Line type="monotone" dataKey="Risk"        stroke="#dc2626" />
        <Line type="monotone" dataKey="Trust"       stroke="#a855f7" />
      </LineChart>
    </ResponsiveContainer>
  )
}
```

### 3. TVL sparkline (single metric)

```tsx
import { LineChart, Line, ResponsiveContainer } from "recharts"

export function TVLSparkline({ vaultId }: { vaultId: string }) {
  const { data } = useSWR(
    `/v1/scores/timeseries/${encodeURIComponent(vaultId)}/C01_USD?days=7`,
    fetcher
  )
  if (!data?.points?.length) return null

  return (
    <ResponsiveContainer width="100%" height={40}>
      <LineChart data={data.points}>
        <Line type="monotone" dataKey="y" stroke="#3b82f6" strokeWidth={2} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  )
}
```

### 4. Top Movers card (socials)

```tsx
export function TopMovers() {
  const { data } = useSWR("/v1/scores/movers?window=24h&direction=down&limit=5", fetcher)
  if (!data?.movers?.length) return <div>No significant moves in 24h</div>

  return (
    <div>
      <h3>📉 Biggest Score Drops (24h)</h3>
      {data.movers.map((m: any) => (
        <div key={m.vault_id} style={{ display: "flex", justifyContent: "space-between" }}>
          <span>{m.name} <small>({m.source})</small></span>
          <span style={{ color: "#dc2626" }}>{m.delta} ({m.before} → {m.after})</span>
        </div>
      ))}
    </div>
  )
}
```

### 5. Live anomaly feed

```tsx
export function AnomaliesFeed() {
  const { data } = useSWR(
    "/v1/scores/anomalies?window=24h&severity=critical",
    fetcher,
    { refreshInterval: 60_000 }
  )
  if (!data?.anomalies?.length) return <div>✅ All clear</div>

  return (
    <ul>
      {data.anomalies.map((a: any) => (
        <li key={a.ts + a.vault_id}>
          <span style={{ color: "#dc2626" }}>🚨 {a.type}</span>
          <strong> {a.name}</strong> — {a.message}
          <small> ({new Date(a.ts).toLocaleString()})</small>
        </li>
      ))}
    </ul>
  )
}
```

### 6. Compare vaults overlay

```tsx
export function CompareVaults({ vaultIds }: { vaultIds: string[] }) {
  const { data } = useSWR(
    `/v1/scores/compare?vault_ids=${vaultIds.join(",")}&days=30`,
    fetcher
  )
  if (!data?.series) return null

  // Pivot series → one row per ts with one column per vault
  const all = new Map<string, any>()
  data.series.forEach((s: any) =>
    s.points.forEach((p: any) => {
      const row = all.get(p.x) ?? { x: p.x }
      row[s.name] = p.y
      all.set(p.x, row)
    })
  )
  const chartData = [...all.values()].sort((a, b) => a.x.localeCompare(b.x))

  const colors = ["#3b82f6", "#10b981", "#dc2626", "#a855f7", "#f59e0b"]
  return (
    <ResponsiveContainer width="100%" height={300}>
      <LineChart data={chartData}>
        <XAxis dataKey="x" />
        <YAxis domain={[0, 100]} />
        <Tooltip />
        <Legend />
        {data.series.map((s: any, i: number) => (
          <Line key={s.vault_id} dataKey={s.name} stroke={colors[i % colors.length]} dot={false} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}
```

---

## Suggested UI placements

- **Vault detail page**: `<ScoreEvolution>` chart at the top, prominent.
  Below it the existing metrics. Add small `<TVLSparkline>` next to "TVL"
  field in the stats row.

- **Vaults list page**: add a `<TVLSparkline>` per row (50-90px wide,
  inline) so users see momentum at a glance.

- **Discovery / explore page**: `<TopMovers>` card on the left rail with
  three tabs — gainers, losers, anomalies.

- **Socials feed (Twitter/Telegram automation)**: poll `/v1/scores/anomalies`
  every 5 min, dedupe by `vault_id + type`, post to Typefully/Telegram
  when a new critical anomaly fires. The `message` field is already
  socials-ready ("TVL dropped 47.2% in 1h").

---

## Polling cadence

| Endpoint                   | Recommended refresh |
| -------------------------- | ------------------- |
| `/history/{vault_id}`      | Once per minute (chart on detail page) |
| `/timeseries/.../C01_USD`  | Once per minute (sparkline)            |
| `/movers`                  | Every 5 min (card)                     |
| `/anomalies?severity=critical` | Every 1 min (feed)                |
| `/leaderboard`             | Every 5 min                            |
| `/compare`                 | Once on user-trigger; cache result     |

The indexer writes new snapshots every 5 minutes (one per vault per hour
bucket), so polling more frequently than 1 minute is wasted bandwidth.

---

## Common gotchas

1. **`vault_id` is `chain_id:address_lowercase`.** Always lowercase and `encodeURIComponent` for `:`.
2. **Times are UTC ISO-8601.** Frontend should convert to user's local TZ.
3. **`yieldo_score` and dimensions are 0–100.** Set Y-axis domain `[0, 100]` for fixed scale.
4. **`metrics.*` sub-fields are nullable** — always null-guard before charting.
5. **`points: []` when window has no data.** Show "No data yet" instead of breaking the chart.
6. **DefiLlama-style pricing fields are USD-denominated already** (no scaling needed).
