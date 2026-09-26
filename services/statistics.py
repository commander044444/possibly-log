"""
Professional Channel Analytics Dashboard image.
Pillow + Matplotlib · real data only · never invents numbers.
"""
from __future__ import annotations

import io
import logging
import os
from datetime import date, timedelta
from typing import Optional, List, Tuple, Any

import database as db

logger = logging.getLogger(__name__)

W, H = 1080, 1350

# ── New Premium Dark Theme ─────────────────────────────
BG = (12, 14, 22)
SURFACE = (22, 26, 38)
SURFACE2 = (30, 36, 52)
BORDER = (48, 56, 78)
ACCENT = (88, 166, 255)
ACCENT_SOFT = (56, 110, 180)
GREEN = (52, 211, 153)
ROSE = (251, 113, 133)
AMBER = (251, 191, 36)
TEXT = (248, 250, 252)
TEXT2 = (203, 213, 225)
MUTED = (148, 163, 184)


def _fmt(n) -> str:
    if n is None:
        return "—"
    try:
        return f"{int(n):,}"
    except Exception:
        return "—"


def _na(v) -> str:
    return "—" if v is None else str(v)


# ── Data ───────────────────────────────────────────────

async def get_channel_stats_summary(channel_id: int) -> dict:
    today = date.today()
    week_start = today - timedelta(days=6)
    month_start = today - timedelta(days=29)

    daily = await db.fetch(
        """
        SELECT * FROM channel_daily_stats
        WHERE channel_id = $1 AND date >= $2
        ORDER BY date
        """,
        channel_id, month_start,
    )

    today_row = next((r for r in daily if r["date"] == today), None)
    week = [r for r in daily if r["date"] >= week_start]

    def sum_col(rows, col):
        return sum((r[col] or 0) for r in rows)

    total_pub = await db.fetchval(
        "SELECT COUNT(*) FROM published_news WHERE channel_id = $1",
        channel_id,
    )

    members_series = []
    for r in daily:
        mc = r.get("members_count")
        if mc is not None:
            members_series.append((r["date"], int(mc)))

    members_now = members_series[-1][1] if members_series else None
    members_7 = None
    members_30 = None
    for d, m in members_series:
        if d <= week_start:
            members_7 = m
        if d <= month_start:
            members_30 = m
    if members_7 is None and members_series:
        members_7 = members_series[0][1]
    if members_30 is None and members_series:
        members_30 = members_series[0][1]

    growth_7 = growth_30 = None
    if members_now is not None and members_7 is not None:
        growth_7 = members_now - members_7
    if members_now is not None and members_30 is not None:
        growth_30 = members_now - members_30

    return {
        "today_messages": (today_row["messages"] if today_row else 0),
        "week_messages": sum_col(week, "messages"),
        "month_messages": sum_col(daily, "messages"),
        "total_messages": int(total_pub or 0) or sum_col(daily, "messages"),
        "photo": sum_col(daily, "photo_count"),
        "video": sum_col(daily, "video_count"),
        "gif": sum_col(daily, "gif_count"),
        "voice": sum_col(daily, "voice_count"),
        "audio": sum_col(daily, "audio_count"),
        "sticker": sum_col(daily, "sticker_count"),
        "file": sum_col(daily, "file_count"),
        "text": sum_col(daily, "text_count"),
        "daily_series": [(r["date"], r["messages"] or 0) for r in daily],
        "members_now": members_now,
        "growth_7d": growth_7,
        "growth_30d": growth_30,
        "joined_7d": growth_7 if growth_7 is not None and growth_7 > 0 else (0 if growth_7 is not None else None),
        "left_7d": (-growth_7 if growth_7 is not None and growth_7 < 0 else (0 if growth_7 is not None else None)),
        "joined_30d": growth_30 if growth_30 is not None and growth_30 > 0 else (0 if growth_30 is not None else None),
        "left_30d": (-growth_30 if growth_30 is not None and growth_30 < 0 else (0 if growth_30 is not None else None)),
        "report_date": today.isoformat(),
    }


async def snapshot_members(channel_id: int, members_count: Optional[int]) -> None:
    if members_count is None:
        return
    try:
        await db.execute(
            """
            INSERT INTO channel_daily_stats (channel_id, date, messages, members_count)
            VALUES ($1, CURRENT_DATE, 0, $2)
            ON CONFLICT (channel_id, date) DO UPDATE SET
                members_count = EXCLUDED.members_count
            """,
            channel_id, int(members_count),
        )
    except Exception as e:
        logger.warning("snapshot_members: %s", e)


# ── Fonts ──────────────────────────────────────────────

def _font_paths():
    candidates_reg = [
        "/usr/share/fonts/SlidesCarnival/google/Cairo/static/Cairo-Regular.ttf",
        "/usr/share/fonts/SlidesCarnival/google/Noto Sans Arabic/static/NotoSansArabic-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    candidates_bold = [
        "/usr/share/fonts/SlidesCarnival/google/Cairo/static/Cairo-Bold.ttf",
        "/usr/share/fonts/SlidesCarnival/google/Noto Sans Arabic/static/NotoSansArabic-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    reg = next((p for p in candidates_reg if os.path.exists(p)), None)
    bold = next((p for p in candidates_bold if os.path.exists(p)), reg)
    return reg, bold


def _fonts():
    from PIL import ImageFont
    reg, bold = _font_paths()

    def make(size, use_bold=False):
        path = bold if use_bold else reg
        try:
            if path:
                return ImageFont.truetype(path, size)
        except Exception:
            pass
        return ImageFont.load_default()

    return {
        "hero": make(52, True),
        "title": make(40, True),
        "subtitle": make(28, False),
        "num": make(56, True),
        "num_sm": make(36, True),
        "label": make(22, False),
        "section": make(26, True),
        "body": make(24, False),
        "small": make(20, False),
        "tiny": make(16, False),
    }


def _round(draw, box, r, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def _center_text(draw, text, cy, font, fill, x0, x1):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = x0 + (x1 - x0 - tw) // 2
    y = cy - th // 2
    draw.text((x, y), text, font=font, fill=fill)
    return th


def _avatar_circle(avatar_bytes: Optional[bytes], size: int = 160):
    from PIL import Image, ImageDraw
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)

    if avatar_bytes:
        try:
            av = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
            av = av.resize((size, size), Image.Resampling.LANCZOS)
            canvas.paste(av, (0, 0), mask)
            # border ring
            ring = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            rd = ImageDraw.Draw(ring)
            rd.ellipse((2, 2, size - 3, size - 3), outline=ACCENT + (255,), width=4)
            return Image.alpha_composite(canvas, ring)
        except Exception as e:
            logger.warning("avatar process: %s", e)

    d = ImageDraw.Draw(canvas)
    d.ellipse((0, 0, size - 1, size - 1), fill=SURFACE2)
    d.ellipse((8, 8, size - 9, size - 9), outline=ACCENT, width=3)
    # simple icon
    cx = cy = size // 2
    d.ellipse((cx - 22, cy - 28, cx + 22, cy - 2), outline=TEXT2, width=3)
    d.arc((cx - 36, cy - 8, cx + 36, cy + 40), start=200, end=340, fill=TEXT2, width=3)
    return canvas


def _activity_chart(series: List[Tuple[Any, int]], w=980, h=280):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image
    import numpy as np

    fig, ax = plt.subplots(figsize=(w / 100, h / 100), dpi=100)
    fig.patch.set_facecolor("#161a26")
    ax.set_facecolor("#161a26")

    today = date.today()
    lookup = {d: m for d, m in series}
    dates = [today - timedelta(days=i) for i in range(29, -1, -1)]
    ys = [lookup.get(d, 0) for d in dates]
    xs = np.arange(30)

    if any(ys):
        ax.fill_between(xs, ys, color="#58A6FF", alpha=0.18)
        ax.plot(xs, ys, color="#58A6FF", linewidth=3.0, solid_capstyle="round")
        peak_i = int(np.argmax(ys))
        ax.scatter([peak_i], [ys[peak_i]], color="#FB7185", s=60, zorder=5)
        ax.set_xlim(-0.5, 29.5)
        ax.set_ylim(0, max(max(ys) * 1.25, 1))
        ticks = [0, 7, 14, 21, 29]
        ax.set_xticks(ticks)
        ax.set_xticklabels([dates[i].strftime("%m/%d") for i in ticks], color="#94A3B8", fontsize=11)
        ax.tick_params(axis="y", colors="#94A3B8", labelsize=11)
        for s in ax.spines.values():
            s.set_color("#303848")
        ax.grid(axis="y", color="#303848", linestyle="--", linewidth=0.7, alpha=0.8)
    else:
        ax.text(0.5, 0.5, "No activity data yet", ha="center", va="center",
                color="#94A3B8", fontsize=16)
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)

    fig.tight_layout(pad=0.5)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, facecolor=fig.get_facecolor(),
                edgecolor="none", bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("RGBA")


def render_stats_image(
    channel_title: str,
    channel_username: Optional[str],
    stats: dict,
    *,
    bio: Optional[str] = None,
    members: Optional[int] = None,
    avatar_bytes: Optional[bytes] = None,
    channel_id: Optional[int] = None,
) -> bytes:
    """1080×1350 Professional Analytics Dashboard PNG."""
    from PIL import Image, ImageDraw

    fonts = _fonts()
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    pad = 36
    y = 28

    # ═══ HEADER ═══════════════════════════════════════
    header_h = 280
    _round(draw, (pad, y, W - pad, y + header_h), 28, SURFACE)

    av = _avatar_circle(avatar_bytes, 150)
    av_x = (W - 150) // 2
    img.paste(av, (av_x, y + 22), av)

    title = (channel_title or "Channel")[:32]
    ty = y + 185
    _center_text(draw, title, ty + 10, fonts["title"], TEXT, pad, W - pad)

    uname = f"@{channel_username}" if channel_username else ""
    if uname:
        _center_text(draw, uname, ty + 48, fonts["subtitle"], ACCENT, pad, W - pad)

    bio_line = (bio or "").replace("\n", " ").strip()[:55]
    if bio_line:
        _center_text(draw, bio_line, ty + 82, fonts["small"], MUTED, pad, W - pad)

    meta = f"Report  {stats.get('report_date', '—')}"
    if channel_id is not None:
        meta += f"   ·   ID {channel_id}"
    _center_text(draw, meta, y + header_h - 22, fonts["tiny"], MUTED, pad, W - pad)

    y += header_h + 24

    # ═══ MEMBERS ROW ══════════════════════════════════
    mem = members if members is not None else stats.get("members_now")
    g7 = stats.get("growth_7d")
    g30 = stats.get("growth_30d")

    def growth_label(v):
        if v is None:
            return "—"
        return f"+{v}" if v > 0 else str(v)

    cards = [
        (_fmt(mem), "Members"),
        (growth_label(g7), "7d Growth"),
        (growth_label(g30), "30d Growth"),
    ]
    gap = 16
    cw = (W - 2 * pad - 2 * gap) // 3
    for i, (val, lbl) in enumerate(cards):
        x0 = pad + i * (cw + gap)
        _round(draw, (x0, y, x0 + cw, y + 120), 22, SURFACE)
        _center_text(draw, val, y + 42, fonts["num"], TEXT if val != "—" else MUTED, x0, x0 + cw)
        _center_text(draw, lbl, y + 92, fonts["label"], MUTED, x0, x0 + cw)

    y += 140

    # ═══ MESSAGE KPIs ═════════════════════════════════
    kpis = [
        (_fmt(stats.get("today_messages", 0)), "Today", ACCENT),
        (_fmt(stats.get("week_messages", 0)), "7 Days", GREEN),
        (_fmt(stats.get("month_messages", 0)), "30 Days", ROSE),
        (_fmt(stats.get("total_messages", 0)), "Total", AMBER),
    ]
    cw = (W - 2 * pad - 3 * gap) // 4
    for i, (val, lbl, color) in enumerate(kpis):
        x0 = pad + i * (cw + gap)
        _round(draw, (x0, y, x0 + cw, y + 130), 22, SURFACE)
        # accent bar top
        draw.rounded_rectangle((x0 + 16, y + 10, x0 + cw - 16, y + 16), radius=3, fill=color)
        _center_text(draw, val, y + 55, fonts["num_sm"], TEXT, x0, x0 + cw)
        _center_text(draw, lbl, y + 100, fonts["label"], MUTED, x0, x0 + cw)

    y += 150

    # ═══ ACTIVITY CHART ═══════════════════════════════
    chart_h = 320
    _round(draw, (pad, y, W - pad, y + chart_h), 24, SURFACE)
    draw.text((pad + 28, y + 18), "Activity  ·  30 Days", font=fonts["section"], fill=TEXT)
    try:
        chart = _activity_chart(stats.get("daily_series") or [], w=960, h=250)
        chart = chart.resize((960, 250), Image.Resampling.LANCZOS)
        img.paste(chart, (pad + 20, y + 55), chart)
    except Exception:
        logger.exception("chart render")
        _center_text(draw, "Chart unavailable", y + chart_h // 2, fonts["body"], MUTED, pad, W - pad)

    y += chart_h + 20

    # ═══ CONTENT GRID ═════════════════════════════════
    section_h = 250
    _round(draw, (pad, y, W - pad, y + section_h), 24, SURFACE)
    draw.text((pad + 28, y + 16), "Content Types  ·  30 Days", font=fonts["section"], fill=TEXT)

    items = [
        ("📝 Text", stats.get("text")),
        ("📷 Photo", stats.get("photo")),
        ("🎥 Video", stats.get("video")),
        ("🎙 Voice", stats.get("voice")),
        ("🎵 Audio", stats.get("audio")),
        ("🎞 GIF", stats.get("gif")),
        ("📁 File", stats.get("file")),
        ("😀 Sticker", stats.get("sticker")),
    ]
    grid_top = y + 60
    cell_w = (W - 2 * pad - 40) // 4
    cell_h = 80
    for i, (lbl, val) in enumerate(items):
        col = i % 4
        row = i // 4
        x0 = pad + 20 + col * cell_w
        y0 = grid_top + row * cell_h
        _round(draw, (x0 + 4, y0, x0 + cell_w - 8, y0 + cell_h - 10), 16, SURFACE2)
        _center_text(draw, _fmt(val), y0 + 28, fonts["num_sm"], TEXT, x0, x0 + cell_w)
        _center_text(draw, lbl, y0 + 58, fonts["tiny"], MUTED, x0, x0 + cell_w)

    # footer
    draw.text(
        (pad, H - 28),
        "Bale News Automation  ·  Real data only",
        font=fonts["tiny"],
        fill=MUTED,
    )

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _fallback_text_image(title: str, stats: dict) -> bytes:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (800, 600), BG)
    d = ImageDraw.Draw(img)
    d.text((40, 40), f"Stats: {title}", fill=TEXT)
    d.text((40, 100), f"Today: {_fmt(stats.get('today_messages'))}", fill=TEXT2)
    d.text((40, 140), f"Week: {_fmt(stats.get('week_messages'))}", fill=TEXT2)
    d.text((40, 180), f"Month: {_fmt(stats.get('month_messages'))}", fill=TEXT2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
