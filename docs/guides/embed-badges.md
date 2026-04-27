---
title: "Embed Score Badges"
description: "Display your vault's live Yieldo score on your own site"
---

Yieldo serves a free, embeddable SVG badge for every vault. Drop it into your landing page, dashboard, or marketing site — it pulls the latest score on every render.

## Quick embed (image)

```html
<img
  src="https://app.yieldo.xyz/api/badge/<vault_id>.svg"
  alt="Rated by Yieldo"
  width="220"
  height="68"
/>
```

`<vault_id>` is the chain-prefixed address of your vault — `<chain_id>:<vault_address_lowercased>`. Examples:

- `1:0xbeef01735c132ada46aa9aa4c54623caa92a64cb` (Steakhouse USDC, Ethereum)
- `8453:0xbeef009f28ccf367444a9f79096862920e025dc1` (Steakhouse Prime EURC, Base)

## iframe variant

If you'd prefer an isolated iframe (e.g. to avoid mixing image-CSP with your own):

```html
<iframe
  src="https://app.yieldo.xyz/api/badge/<vault_id>.svg"
  width="220"
  height="68"
  frameborder="0"
  scrolling="no"
  title="Yieldo Score"
></iframe>
```

## Variants

| Query param | Values | Description |
| --- | --- | --- |
| `theme` | `light` (default), `dark` | Background tone |
| `style` | `compact` (default, 220×68), `detailed` (320×120) | Layout |

Examples:

```
# Dark compact
https://app.yieldo.xyz/api/badge/1:0xbeef01735c132ada46aa9aa4c54623caa92a64cb.svg?theme=dark

# Detailed (with sub-score breakdown)
https://app.yieldo.xyz/api/badge/1:0xbeef01735c132ada46aa9aa4c54623caa92a64cb.svg?style=detailed
```

## Behaviour

- **Live data**: The badge renders the current score on each request. We cache for 5 minutes at the CDN edge, so updates propagate within minutes.
- **Color tier**: Score ≥80 is green, 60-79 gold, 40-59 amber, <40 red.
- **No auth**: The endpoint is public.
- **CORS**: All origins are allowed (`Access-Control-Allow-Origin: *`).

## Linking the badge

To make the badge clickable, wrap the `<img>` in an anchor pointing to the vault page:

```html
<a href="https://app.yieldo.xyz/vault/<vault_id>" target="_blank" rel="noopener noreferrer">
  <img
    src="https://app.yieldo.xyz/api/badge/<vault_id>.svg"
    alt="View on Yieldo"
    width="220"
    height="68"
  />
</a>
```

## Markdown / GitHub

Same image works in any Markdown renderer (READMEs, blog posts, Notion):

```markdown
[![Yieldo Score](https://app.yieldo.xyz/api/badge/<vault_id>.svg)](https://app.yieldo.xyz/vault/<vault_id>)
```
