"""Open Graph card renderer for vault score pages.

Renders a 1200×630 PNG image that previews a vault's Yieldo Score when
someone pastes an `app.yieldo.xyz/vault/{id}` link into X/Twitter, Telegram,
Discord, Farcaster, Slack, etc. Each platform reads the page's
`<meta property="og:image">` URL — when that URL points here, the preview
*is* marketing.

Design language: dark purple gradient (matches the brand's `purpleGrad`),
oversized score on the left, sub-score chips on the right, vault name
underneath. Looks like a finished product card, not a debug page.

Implementation notes:
- Pure Pillow. No headless browser, no Cairo/SVG dep. Renders in ~40-80ms
  on modern hardware. That's slow enough that we cache aggressively at the
  edge (see route handler) but fast enough that a cold-cache OG scrape
  doesn't time out the bot.
- Fonts: tries system DejaVu/Arial/Inter and falls back to Pillow's built-in
  bitmap font. The card will look noticeably worse on the bitmap fallback,
  but it won't crash — so the endpoint stays live even if font files move.
- No external network calls during render. The caller must hand us a fully
  populated context dict.
"""
from __future__ import annotations

import io
import logging
import os
from typing import Any, Optional

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Canvas + brand
# --------------------------------------------------------------------------

# X uses 1200×630 for large summary cards; Telegram/Discord crop centrally
# from the same aspect. Going larger wastes bytes; smaller and X downsizes
# our text. 1200×630 it is.
W, H = 1200, 630

# Brand palette — kept in sync with `C` in the React frontend.
DEEP_PURPLE = (34, 6, 79)        # gradient anchor (top-left)
MID_PURPLE  = (75, 12, 166)      # #4B0CA6
PURPLE      = (122, 28, 203)     # #7A1CCB
LIGHT_PURPLE = (158, 59, 255)    # gradient anchor (bottom-right)
WHITE       = (255, 255, 255)
WHITE_DIM   = (255, 255, 255, 180)
WHITE_DIM2  = (255, 255, 255, 110)
GREEN       = (66, 213, 110)
GOLD        = (220, 184, 30)
AMBER       = (240, 150, 30)
RED         = (240, 80, 80)
GREY        = (180, 178, 200)


def _score_color(score: int) -> tuple[int, int, int]:
    if score >= 80:
        return GREEN
    if score >= 60:
        return GOLD
    if score >= 40:
        return AMBER
    return RED


# --------------------------------------------------------------------------
# Font loading
# --------------------------------------------------------------------------

# Search order: bundled (if shipped later) → common system paths → bitmap
# fallback. We bias toward bold variants because OG cards are tiny on phones
# and a regular-weight body would disappear.
_FONT_CANDIDATES_BOLD = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)
_FONT_CANDIDATES_REG = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)


def _resolve_font_path(candidates: tuple[str, ...]) -> Optional[str]:
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


# Cache resolved paths to avoid statting on every request.
_BOLD_PATH = _resolve_font_path(_FONT_CANDIDATES_BOLD)
_REG_PATH  = _resolve_font_path(_FONT_CANDIDATES_REG)


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    path = _BOLD_PATH if bold else _REG_PATH
    if path is not None:
        try:
            return ImageFont.truetype(path, size)
        except Exception as e:
            logger.warning("Failed to load font %s at size %d: %s", path, size, e)
    # Pillow's built-in font is a 10px bitmap — readable but tiny. Last resort.
    return ImageFont.load_default()


# --------------------------------------------------------------------------
# Drawing helpers
# --------------------------------------------------------------------------

def _gradient_background() -> Image.Image:
    """Diagonal gradient deep-purple → light-purple. Built by lerping rows
    so it's pure Python (no NumPy dep) and only runs once per render."""
    bg = Image.new("RGB", (W, H), MID_PURPLE)
    px = bg.load()
    # Diagonal lerp factor along the (1,1) vector, normalized.
    diag = W + H
    for y in range(H):
        for x in range(W):
            t = (x + y) / diag
            r = int(DEEP_PURPLE[0] * (1 - t) + LIGHT_PURPLE[0] * t)
            g = int(DEEP_PURPLE[1] * (1 - t) + LIGHT_PURPLE[1] * t)
            b = int(DEEP_PURPLE[2] * (1 - t) + LIGHT_PURPLE[2] * t)
            px[x, y] = (r, g, b)
    return bg


def _rounded_rect(draw: ImageDraw.ImageDraw, xy, radius: int, fill, outline=None, width: int = 0):
    """Wrapper around Pillow's `rounded_rectangle` so we keep one canonical
    signature in the codebase."""
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def _text_w(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _truncate(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int) -> str:
    """Cut text with a trailing ellipsis if it overflows. Naive char-by-char
    walk — fine for vault names (under 60 chars typically)."""
    if _text_w(draw, text, font) <= max_w:
        return text
    while len(text) > 1 and _text_w(draw, text + "…", font) > max_w:
        text = text[:-1]
    return text + "…"


# --------------------------------------------------------------------------
# Public renderer
# --------------------------------------------------------------------------

def render_card(
    *,
    vault_name: str,
    score: Optional[int],
    sub_scores: Optional[dict[str, int]] = None,
    curator: Optional[str] = None,
    chain: Optional[str] = None,
    asset: Optional[str] = None,
    protocol: Optional[str] = None,
    apy: Optional[float] = None,
) -> bytes:
    """Render a vault OG card and return PNG bytes. All score/breakdown
    values are optional — the card degrades gracefully if e.g. the indexer
    hasn't snapshotted this vault yet."""
    bg = _gradient_background()
    draw = ImageDraw.Draw(bg, "RGBA")

    # ---- Top bar: brand + URL --------------------------------------------
    brand_font = _font(28, bold=True)
    url_font = _font(20, bold=False)
    # Brand mark — purple square with a white Y. Subtle but recognizable.
    _rounded_rect(draw, (60, 50, 60 + 52, 50 + 52), radius=12, fill=LIGHT_PURPLE)
    y_font = _font(36, bold=True)
    yw = _text_w(draw, "Y", y_font)
    draw.text((60 + (52 - yw) // 2, 50 + 4), "Y", fill=WHITE, font=y_font)
    draw.text((130, 60), "YIELDO", fill=WHITE, font=brand_font)
    # Right-aligned URL hint
    url = "app.yieldo.xyz"
    uw = _text_w(draw, url, url_font)
    draw.text((W - 60 - uw, 68), url, fill=WHITE_DIM, font=url_font)

    # ---- Center-left: big score number -----------------------------------
    score_label_font = _font(22, bold=True)
    score_num_font = _font(220, bold=True)
    score_max_font = _font(60, bold=True)
    draw.text((60, 180), "YIELDO SCORE", fill=WHITE_DIM2, font=score_label_font)

    if score is None:
        # Pre-score placeholder — happens when the indexer hasn't snapshotted
        # the vault yet (first 24h post-listing).
        placeholder_font = _font(120, bold=True)
        draw.text((60, 220), "—", fill=WHITE_DIM, font=placeholder_font)
    else:
        # Score colored by band. The "/100" stays neutral so the band-color
        # reads as the headline, not a "/100" decoration.
        col = _score_color(score)
        score_str = str(score)
        draw.text((60, 220), score_str, fill=col, font=score_num_font)
        sw = _text_w(draw, score_str, score_num_font)
        draw.text((60 + sw + 12, 380), "/100", fill=WHITE_DIM, font=score_max_font)

    # ---- Right column: sub-score chips -----------------------------------
    if sub_scores:
        chip_label_font = _font(18, bold=True)
        chip_val_font = _font(48, bold=True)
        chip_x = 720
        chip_y = 180
        chip_w = 200
        chip_h = 84
        chip_gap = 12
        labels = (
            ("CAPITAL", sub_scores.get("capital")),
            ("PERFORMANCE", sub_scores.get("performance")),
            ("RISK", sub_scores.get("risk")),
            ("TRUST", sub_scores.get("trust")),
        )
        for i, (label, val) in enumerate(labels):
            row, col_i = divmod(i, 2)
            x = chip_x + col_i * (chip_w + chip_gap)
            y = chip_y + row * (chip_h + chip_gap)
            # Chip body — translucent white over the gradient.
            _rounded_rect(draw, (x, y, x + chip_w, y + chip_h), radius=10, fill=(255, 255, 255, 28))
            draw.text((x + 14, y + 12), label, fill=WHITE_DIM2, font=chip_label_font)
            val_str = str(val) if isinstance(val, int) else "—"
            val_col = _score_color(val) if isinstance(val, int) else WHITE_DIM
            draw.text((x + 14, y + 32), val_str, fill=val_col, font=chip_val_font)

    # ---- Bottom band: vault name + meta ----------------------------------
    name_font = _font(56, bold=True)
    meta_font = _font(24, bold=False)
    # Background bar so the name stays readable over the gradient bottom-right
    # (which gets lightest there).
    _rounded_rect(draw, (60, 470, W - 60, 570), radius=18, fill=(15, 5, 35, 200))

    truncated_name = _truncate(draw, vault_name, name_font, W - 60 - 60 - 40)
    draw.text((80, 482), truncated_name, fill=WHITE, font=name_font)

    # Meta line: "Curator · Chain · Asset · APY" — only include parts we have.
    meta_parts: list[str] = []
    if curator:  meta_parts.append(curator)
    if protocol: meta_parts.append(protocol)
    if chain:    meta_parts.append(chain)
    if asset:    meta_parts.append(asset.upper())
    if apy is not None:
        try:
            meta_parts.append(f"{float(apy):.2f}% APY")
        except (TypeError, ValueError):
            pass
    if meta_parts:
        meta_str = "  ·  ".join(meta_parts)
        meta_str = _truncate(draw, meta_str, meta_font, W - 80 - 80)
        draw.text((80, 540), meta_str, fill=WHITE_DIM, font=meta_font)

    # ---- Export ----------------------------------------------------------
    buf = io.BytesIO()
    bg.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
