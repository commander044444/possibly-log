"""
Professional channel analytics card (Pillow + Matplotlib).
Always free for channel owners. Never invents fake numbers.
"""
from __future__ import annotations

import io
import logging
import math
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Tuple, List, Any

import database as db

logger = logging.getLogger(__name__)

# Canvas
W, H = 1080, 1350

# Palette — modern dark premium
BG = (18, 20, 32)
CARD = (28, 32, 48)
CARD2 = (36, 42, 62)
ACCENT = (76, 139, 245)       # blue
ACCENT2 = (233, 69, 96)       # rose
GREEN = (46, 204, 113)
MUTED = (140, 150, 170)
WHITE = (245, 247, 250)
SOFT = (200, 210, 230)


def _na(v) -> str:
    if v is None:
        return "N/A"
    return str(v)


def _fmt(n) -> str:
    if n is None:
        return "N/A"
    try:
        n = int(n)
    except Exception:
        return "N/A"
    return f"{n:,}"


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
    month = list(daily)

    def sum_col(rows, col):
        return sum((r[col] or 0) for r in rows)

    # total all-time messages from published_news if available
    total_pub = await db.fetchval(
        "SELECT COUNT(*) FROM published_news WHERE channel_id = $1",
        channel_id,
    )

    # member snapshots if column exists
    members_series = []
    try:
        members_series = [
            (r["date"], r.get("members_count"))
            for r in daily
            if r.get("members_count") is not None
        ]
    except Exception:
        members_series = []

    members_now = None
    members_7d_ago = None
    members_30d_ago = None
    if members_series:
        members_now = members_series[-1][1]
        for d, m in members_series:
            if d <= week_start and members_7d_ago is None:
                members_7d_ago = m
            if d <= month_start and members_30d_ago is None:
                members_30d_ago = m
        # if first rows are after week_start, use earliest
        if members_7d_ago is None and members_series:
            members_7d_ago = members_series[0][1]
        if members_30d_ago is None and members_series:
            members_30d_ago = members_series[0][1]

    joined_7 = left_7 = joined_30 = left_30 = None
    if members_now is not None and members_7d_ago is not None:
        delta7 = members_now - members_7d_ago
        if delta7 >= 0:
            joined_7, left_7 = delta7, 0
        else:
            joined_7, left_7 = 0, -delta7
    if members_now is not None and members_30d_ago is not None:
        delta30 = members_now - members_30d_ago
        if delta30 >= 0:
            joined_30, left_30 = delta30, 0
        else:
            joined_30, left_30 = 0, -delta30

    return {
        "today_messages": (today_row["messages"] if today_row else 0),
        "week_messages": sum_col(week, "messages"),
        "month_messages": sum_col(month, "messages"),
        "total_messages": int(total_pub or 0) or sum_col(month, "messages"),
        "photo": sum_col(month, "photo_count"),
        "video": sum_col(month, "video_count"),
        "gif": sum_col(month, "gif_count"),
        "voice": sum_col(month, "voice_count"),
        "audio": sum_col(month, "audio_count"),
        "sticker": sum_col(month, "sticker_count"),
        "file": sum_col(month, "file_count"),
        "text": sum_col(month, "text_count"),
        "daily_series": [(r["date"], r["messages"] or 0) for r in daily],
        "members_now": members_now,
        "joined_7d": joined_7,
        "left_7d": left_7,
        "joined_30d": joined_30,
        "left_30d": left_30,
        "report_date": today.isoformat(),
    }


async def snapshot_members(channel_id: int, members_count: Optional[int]) -> None:
    """Store today's member count if known (for future join/leave deltas)."""
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
        # column may not exist yet
        logger.warning("snapshot_members failed: %s", e)


def _load_fonts():
    from PIL import ImageFont
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    bold_c = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    path = next((c for c in candidates if __import__("os").path.exists(c)), None)
    bold = next((c for c in bold_c if __import__("os").path.exists(c)), path)

    def f(size, b=False):
        try:
            return ImageFont.truetype(bold if b else path, size) if path else ImageFont.load_default()
        except Exception:
            return ImageFont.load_default()

    return {
        "title": f(42, True),
        "subtitle": f(26, False),
        "card_val": f(40, True),
        "card_lbl": f(20, False),
        "section": f(24, True),
        "body": f(22, False),
        "small": f(18, False),
        "tiny": f(15, False),
    }


def _rounded_rect(draw, xy, radius, fill):
    draw.rounded_rectangle(xy, radius=radius, fill=fill)


def _circle_avatar(base_img, avatar_bytes: Optional[bytes], size: int = 140):
    from PIL import Image, ImageDraw
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    md.ellipse((0, 0, size - 1, size - 1), fill=255)

    if avatar_bytes:
        try:
            av = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
            av = av.resize((size, size), Image.Resampling.LANCZOS)
            canvas.paste(av, (0, 0), mask)
            return canvas
        except Exception:
            pass

    # default gradient-ish avatar
    d = ImageDraw.Draw(canvas)
    d.ellipse((0, 0, size - 1, size - 1), fill=ACCENT)
    d.ellipse((20, 20, size - 21, size - 21), fill=CARD2)
    # simple broadcast icon
    cx, cy = size // 2, size // 2
    d.ellipse((cx - 18, cy - 18, cx + 18, cy + 18), outline=WHITE, width=3)
    d.ellipse((cx - 8, cy - 8, cx + 8, cy + 8), fill=WHITE)
    return canvas


def _make_activity_chart(daily_series: List[Tuple[Any, int]], width=980, height=260) -> "Image.Image":
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image
    import numpy as np

    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    fig.patch.set_facecolor("#1c2030")
    ax.set_facecolor("#1c2030")

    if daily_series:
        # fill missing days for last 30
        today = date.today()
        lookup = {d: m for d, m in daily_series}
        xs_dates = [today - timedelta(days=i) for i in range(29, -1, -1)]
        ys = [lookup.get(d, 0) for d in xs_dates]
        xs = np.arange(len(ys))
        ax.fill_between(xs, ys, color="#4C8BF5", alpha=0.25)
        ax.plot(xs, ys, color="#4C8BF5", linewidth=2.2)
        ax.scatter(xs[::5], [ys[i] for i in range(0, len(ys), 5)], color="#E94560", s=18, zorder=5)
        ax.set_xlim(-0.5, len(ys) - 0.5)
        ymax = max(ys) if ys else 1
        ax.set_ylim(0, max(ymax * 1.15, 1))
        # sparse x labels
        tick_idx = list(range(0, 30, 5))
        ax.set_xticks(tick_idx)
        ax.set_xticklabels([xs_dates[i].strftime("%m/%d") for i in tick_idx], color="#8C96AA", fontsize=8)
        ax.tick_params(axis="y", colors="#8C96AA", labelsize=8)
        for spine in ax.spines.values():
            spine.set_color("#2A3148")
        ax.grid(axis="y", color="#2A3148", linestyle="--", linewidth=0.6)
    else:
        ax.text(0.5, 0.5, "N/A", ha="center", va="center", color="#8C96AA", fontsize=16)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

    fig.tight_layout(pad=0.4)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("RGBA")


def _make_content_chart(stats: dict, width=980, height=220) -> "Image.Image":
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image

    labels = ["Text", "Photo", "Video", "GIF", "Voice", "Audio", "File", "Sticker"]
    keys = ["text", "photo", "video", "gif", "voice", "audio", "file", "sticker"]
    values = [int(stats.get(k) or 0) for k in keys]
    colors = ["#4C8BF5", "#2ECC71", "#E94560", "#9B59B6", "#F39C12", "#1ABC9C", "#95A5A6", "#E67E22"]

    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    fig.patch.set_facecolor("#1c2030")
    ax.set_facecolor("#1c2030")

    if sum(values) > 0:
        bars = ax.barh(labels, values, color=colors, height=0.65)
        ax.tick_params(axis="y", colors="#C8D2E6", labelsize=9)
        ax.tick_params(axis="x", colors="#8C96AA", labelsize=8)
        for spine in ax.spines.values():
            spine.set_color("#2A3148")
        ax.grid(axis="x", color="#2A3148", linestyle="--", linewidth=0.5)
        xmax = max(values)
        ax.set_xlim(0, xmax * 1.2 if xmax else 1)
        for bar, v in zip(bars, values):
            ax.text(v + xmax * 0.02, bar.get_y() + bar.get_height() / 2,
                    str(v), va="center", color="#C8D2E6", fontsize=8)
    else:
        ax.text(0.5, 0.5, "N/A", ha="center", va="center", color="#8C96AA", fontsize=16)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

    fig.tight_layout(pad=0.4)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, facecolor=fig.get_facecolor(), edgecolor="none")
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
) -> bytes:
    """
    Professional 1080×1350 analytics card. PNG bytes. No fake data.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageFilter
    except ImportError:
        return _fallback_text_image(channel_title, stats)

    fonts = _load_fonts()
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # subtle top gradient band
    for i in range(220):
        ratio = i / 220
        r = int(BG[0] + (CARD2[0] - BG[0]) * (1 - ratio) * 0.5)
        g = int(BG[1] + (CARD2[1] - BG[1]) * (1 - ratio) * 0.5)
        b = int(BG[2] + (ACCENT[2] - BG[2]) * (1 - ratio) * 0.15)
        draw.line([(0, i), (W, i)], fill=(r, g, b))

    pad = 40
    y = 36

    # Header card
    _rounded_rect(draw, (pad, y, W - pad, y + 200), 24, CARD)
    avatar = _circle_avatar(img, avatar_bytes, 128)
    img.paste(avatar, (pad + 28, y + 36), avatar)

    title = (channel_title or "Channel")[:36]
    uname = f"@{channel_username}" if channel_username else ""
    draw.text((pad + 180, y + 40), title, font=fonts["title"], fill=WHITE)
    if uname:
        draw.text((pad + 180, y + 92), uname, font=fonts["subtitle"], fill=ACCENT)
    bio_txt = (bio or "").strip()
    if bio_txt:
        bio_txt = bio_txt.replace("\n", " ")[:70]
        draw.text((pad + 180, y + 130), bio_txt, font=fonts["small"], fill=MUTED)

    report = stats.get("report_date") or date.today().isoformat()
    draw.text((pad + 180, y + 160), f"Report · {report}", font=fonts["tiny"], fill=MUTED)

    y += 220

    # Members row
    mem = members if members is not None else stats.get("members_now")
    j7 = stats.get("joined_7d")
    l7 = stats.get("left_7d")
    j30 = stats.get("joined_30d")
    l30 = stats.get("left_30d")

    cards = [
        ("Members", _fmt(mem)),
        ("+7d", _fmt(j7) if j7 is not None else "N/A"),
        ("-7d", _fmt(l7) if l7 is not None else "N/A"),
        ("+30d", _fmt(j30) if j30 is not None else "N/A"),
    ]
    gap = 16
    cw = (W - 2 * pad - 3 * gap) // 4
    for i, (lbl, val) in enumerate(cards):
        x0 = pad + i * (cw + gap)
        _rounded_rect(draw, (x0, y, x0 + cw, y + 100), 18, CARD)
        # center text roughly
        draw.text((x0 + 16, y + 18), lbl, font=fonts["card_lbl"], fill=MUTED)
        draw.text((x0 + 16, y + 48), val, font=fonts["card_val"], fill=WHITE if val != "N/A" else MUTED)

    y += 120

    # Activity KPI cards
    kpis = [
        ("Today", _fmt(stats.get("today_messages", 0)), ACCENT),
        ("7 Days", _fmt(stats.get("week_messages", 0)), GREEN),
        ("30 Days", _fmt(stats.get("month_messages", 0)), ACCENT2),
        ("Total", _fmt(stats.get("total_messages", 0)), SOFT),
    ]
    cw = (W - 2 * pad - 3 * gap) // 4
    for i, (lbl, val, color) in enumerate(kpis):
        x0 = pad + i * (cw + gap)
        _rounded_rect(draw, (x0, y, x0 + cw, y + 110), 18, CARD)
        draw.rectangle((x0, y, x0 + 6, y + 110), fill=color)
        draw.text((x0 + 18, y + 22), lbl, font=fonts["card_lbl"], fill=MUTED)
        draw.text((x0 + 18, y + 52), val, font=fonts["card_val"], fill=WHITE)

    y += 130

    # Activity chart section
    _rounded_rect(draw, (pad, y, W - pad, y + 310), 22, CARD)
    draw.text((pad + 24, y + 16), "Activity · 30 Days", font=fonts["section"], fill=WHITE)
    chart = _make_activity_chart(stats.get("daily_series") or [], width=960, height=250)
    chart = chart.resize((960, 250), Image.Resampling.LANCZOS)
    img.paste(chart, (pad + 20, y + 50), chart)

    y += 330

    # Content type chart
    _rounded_rect(draw, (pad, y, W - pad, y + 280), 22, CARD)
    draw.text((pad + 24, y + 16), "Content Types · 30 Days", font=fonts["section"], fill=WHITE)
    cchart = _make_content_chart(stats, width=960, height=220)
    cchart = cchart.resize((960, 220), Image.Resampling.LANCZOS)
    img.paste(cchart, (pad + 20, y + 48), cchart)

    y += 300

    # Footer content grid (compact numbers)
    types = [
        ("Text", stats.get("text")),
        ("Photo", stats.get("photo")),
        ("Video", stats.get("video")),
        ("Voice", stats.get("voice")),
        ("GIF", stats.get("gif")),
        ("Audio", stats.get("audio")),
        ("File", stats.get("file")),
        ("Sticker", stats.get("sticker")),
    ]
    _rounded_rect(draw, (pad, y, W - pad, min(H - 30, y + 140)), 18, CARD)
    for i, (lbl, val) in enumerate(types):
        col = i % 4
        row = i // 4
        x0 = pad + 24 + col * 250
        y0 = y + 20 + row * 55
        draw.text((x0, y0), lbl, font=fonts["small"], fill=MUTED)
        draw.text((x0 + 100, y0), _fmt(val), font=fonts["body"], fill=WHITE)

    # tiny footer
    draw.text((pad, H - 28), "Bale News Automation · Analytics", font=fonts["tiny"], fill=MUTED)

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _fallback_text_image(title: str, stats: dict) -> bytes:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (800, 600), BG)
    d = ImageDraw.Draw(img)
    d.text((30, 30), f"Stats: {title}", fill=WHITE)
    d.text((30, 80), f"Today: {_fmt(stats.get('today_messages'))}", fill=SOFT)
    d.text((30, 120), f"Week: {_fmt(stats.get('week_messages'))}", fill=SOFT)
    d.text((30, 160), f"Month: {_fmt(stats.get('month_messages'))}", fill=SOFT)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
