"""
Channel Analytics Dashboard — large type, high contrast, real data only.
Canvas 1242 × 1600 (mobile-sharp). Avatar from real ChatPhoto bytes.
"""
from __future__ import annotations

import io
import logging
import os
from datetime import date, timedelta
from typing import Optional, List, Tuple, Any

import database as db

logger = logging.getLogger(__name__)

# Larger canvas so text stays readable after Bale compression
W, H = 1440, 1860

BG = (10, 12, 18)
SURFACE = (24, 28, 42)
SURFACE2 = (34, 40, 58)
ACCENT = (96, 165, 250)
GREEN = (52, 211, 153)
ROSE = (251, 113, 133)
AMBER = (251, 191, 36)
TEXT = (255, 255, 255)
TEXT2 = (226, 232, 240)
MUTED = (156, 163, 175)


def _fmt(n) -> str:
    if n is None:
        return "—"
    try:
        return f"{int(n):,}"
    except Exception:
        return "—"


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
    members_7 = members_30 = None
    for d, m in members_series:
        if d <= week_start:
            members_7 = m
        if d <= month_start:
            members_30 = m
    if members_7 is None and members_series:
        members_7 = members_series[0][1]
    if members_30 is None and members_series:
        members_30 = members_series[0][1]

    growth_7 = (members_now - members_7) if (members_now is not None and members_7 is not None) else None
    growth_30 = (members_now - members_30) if (members_now is not None and members_30 is not None) else None

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


def _font_paths():
    bold_c = [
        "/usr/share/fonts/SlidesCarnival/google/Cairo/static/Cairo-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    reg_c = [
        "/usr/share/fonts/SlidesCarnival/google/Cairo/static/Cairo-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    bold = next((p for p in bold_c if os.path.exists(p)), None)
    reg = next((p for p in reg_c if os.path.exists(p)), bold)
    return reg, bold


def _fonts():
    from PIL import ImageFont
    reg, bold = _font_paths()

    def f(size, b=False):
        path = bold if b else reg
        try:
            if path:
                return ImageFont.truetype(path, size)
        except Exception:
            pass
        return ImageFont.load_default()

    # LARGE sizes for mobile readability after messenger compression
    return {
        "title": f(68, True),
        "uname": f(42, False),
        "bio": f(32, False),
        "num_xl": f(88, True),
        "num": f(72, True),
        "num_md": f(56, True),
        "label": f(32, False),
        "section": f(40, True),
        "small": f(30, False),
        "tiny": f(26, False),
    }


def _round(draw, box, r, fill):
    draw.rounded_rectangle(box, radius=r, fill=fill)


def _center(draw, text, cy, font, fill, x0, x1):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text((x0 + (x1 - x0 - tw) // 2, cy - th // 2), text, font=font, fill=fill)
    return th


def _avatar(avatar_bytes: Optional[bytes], size: int = 260):
    from PIL import Image, ImageDraw
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)

    if avatar_bytes and len(avatar_bytes) > 100:
        try:
            av = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
            av = av.resize((size, size), Image.Resampling.LANCZOS)
            out.paste(av, (0, 0), mask)
            ring = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            rd = ImageDraw.Draw(ring)
            rd.ellipse((3, 3, size - 4, size - 4), outline=ACCENT + (255,), width=6)
            return Image.alpha_composite(out, ring)
        except Exception as e:
            logger.warning("avatar process failed: %s", e)

    d = ImageDraw.Draw(out)
    d.ellipse((0, 0, size - 1, size - 1), fill=SURFACE2)
    d.ellipse((6, 6, size - 7, size - 7), outline=ACCENT, width=5)
    cx = cy = size // 2
    d.ellipse((cx - 28, cy - 36, cx + 28, cy - 4), outline=TEXT2, width=4)
    d.arc((cx - 48, cy - 10, cx + 48, cy + 50), 200, 340, fill=TEXT2, width=4)
    return out


def _chart(series: List[Tuple[Any, int]], w=1140, h=320):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image
    import numpy as np

    fig, ax = plt.subplots(figsize=(w / 100, h / 100), dpi=120)
    fig.patch.set_facecolor("#181c2a")
    ax.set_facecolor("#181c2a")

    today = date.today()
    lookup = {d: m for d, m in series}
    dates = [today - timedelta(days=i) for i in range(29, -1, -1)]
    ys = [lookup.get(d, 0) for d in dates]
    xs = np.arange(30)

    if any(ys):
        ax.fill_between(xs, ys, color="#60A5FA", alpha=0.22)
        ax.plot(xs, ys, color="#60A5FA", linewidth=4.0, solid_capstyle="round")
        peak = int(np.argmax(ys))
        ax.scatter([peak], [ys[peak]], color="#FB7185", s=90, zorder=5)
        ax.set_xlim(-0.5, 29.5)
        ax.set_ylim(0, max(max(ys) * 1.3, 1))
        ticks = [0, 7, 14, 21, 29]
        ax.set_xticks(ticks)
        ax.set_xticklabels([dates[i].strftime("%m/%d") for i in ticks],
                           color="#9CA3AF", fontsize=14, fontweight="bold")
        ax.tick_params(axis="y", colors="#9CA3AF", labelsize=14)
        for s in ax.spines.values():
            s.set_color("#3A4158")
            s.set_linewidth(1.2)
        ax.grid(axis="y", color="#3A4158", linestyle="--", linewidth=0.9)
    else:
        ax.text(0.5, 0.5, "No data yet", ha="center", va="center",
                color="#9CA3AF", fontsize=22, fontweight="bold")
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)

    fig.tight_layout(pad=0.6)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, facecolor=fig.get_facecolor(),
                edgecolor="none", bbox_inches="tight", pad_inches=0.2)
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
    from PIL import Image, ImageDraw

    fonts = _fonts()
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    pad = 40
    y = 36

    # ── HEADER ────────────────────────────────────────
    hh = 420
    _round(draw, (pad, y, W - pad, y + hh), 32, SURFACE)

    av_size = 260
    av = _avatar(avatar_bytes, av_size)
    img.paste(av, ((W - av_size) // 2, y + 28), av)

    title = (channel_title or "Channel")[:28]
    _center(draw, title, y + 310, fonts["title"], TEXT, pad, W - pad)

    if channel_username:
        _center(draw, f"@{channel_username}", y + 365, fonts["uname"], ACCENT, pad, W - pad)

    y += hh + 20

    # bio + meta under header
    bio_line = (bio or "").replace("\n", " ").strip()[:60]
    if bio_line:
        _center(draw, bio_line, y + 8, fonts["bio"], MUTED, pad, W - pad)
        y += 40
    meta = f"{stats.get('report_date', '—')}"
    if channel_id is not None:
        meta += f"   ·   ID {channel_id}"
    _center(draw, meta, y + 8, fonts["tiny"], MUTED, pad, W - pad)
    y += 36

    # ── MEMBERS ───────────────────────────────────────
    mem = members if members is not None else stats.get("members_now")
    g7 = stats.get("growth_7d")
    g30 = stats.get("growth_30d")

    def gtxt(v):
        if v is None:
            return "—"
        return f"+{v}" if v > 0 else str(v)

    row = [
        (_fmt(mem), "MEMBERS"),
        (gtxt(g7), "7d GROWTH"),
        (gtxt(g30), "30d GROWTH"),
    ]
    gap = 18
    cw = (W - 2 * pad - 2 * gap) // 3
    for i, (val, lbl) in enumerate(row):
        x0 = pad + i * (cw + gap)
        _round(draw, (x0, y, x0 + cw, y + 170), 28, SURFACE)
        _center(draw, val, y + 65, fonts["num"], TEXT if val != "—" else MUTED, x0, x0 + cw)
        _center(draw, lbl, y + 130, fonts["label"], MUTED, x0, x0 + cw)
    y += 190

    # ── MESSAGE KPIs ──────────────────────────────────
    kpis = [
        (_fmt(stats.get("today_messages", 0)), "TODAY", ACCENT),
        (_fmt(stats.get("week_messages", 0)), "7 DAYS", GREEN),
        (_fmt(stats.get("month_messages", 0)), "30 DAYS", ROSE),
        (_fmt(stats.get("total_messages", 0)), "TOTAL", AMBER),
    ]
    cw = (W - 2 * pad - 3 * gap) // 4
    for i, (val, lbl, color) in enumerate(kpis):
        x0 = pad + i * (cw + gap)
        _round(draw, (x0, y, x0 + cw, y + 180), 28, SURFACE)
        draw.rounded_rectangle((x0 + 20, y + 14, x0 + cw - 20, y + 22), radius=4, fill=color)
        _center(draw, val, y + 85, fonts["num_md"], TEXT, x0, x0 + cw)
        _center(draw, lbl, y + 145, fonts["label"], MUTED, x0, x0 + cw)
    y += 200

    # ── CHART ─────────────────────────────────────────
    ch = 380
    _round(draw, (pad, y, W - pad, y + ch), 28, SURFACE)
    draw.text((pad + 32, y + 22), "ACTIVITY · 30 DAYS", font=fonts["section"], fill=TEXT)
    try:
        chart = _chart(stats.get("daily_series") or [])
        chart = chart.resize((W - 2 * pad - 48, 300), Image.Resampling.LANCZOS)
        img.paste(chart, (pad + 24, y + 65), chart)
    except Exception:
        logger.exception("chart")
        _center(draw, "Chart unavailable", y + ch // 2, fonts["label"], MUTED, pad, W - pad)
    y += ch + 20

    # ── CONTENT ───────────────────────────────────────
    _round(draw, (pad, y, W - pad, min(H - 40, y + 280)), 28, SURFACE)
    draw.text((pad + 32, y + 20), "CONTENT · 30 DAYS", font=fonts["section"], fill=TEXT)

    items = [
        ("TEXT", stats.get("text")),
        ("PHOTO", stats.get("photo")),
        ("VIDEO", stats.get("video")),
        ("VOICE", stats.get("voice")),
        ("AUDIO", stats.get("audio")),
        ("GIF", stats.get("gif")),
        ("FILE", stats.get("file")),
        ("STICKER", stats.get("sticker")),
    ]
    cell_w = (W - 2 * pad - 48) // 4
    for i, (lbl, val) in enumerate(items):
        col, rowi = i % 4, i // 4
        x0 = pad + 24 + col * cell_w
        y0 = y + 70 + rowi * 95
        _round(draw, (x0 + 6, y0, x0 + cell_w - 12, y0 + 85), 18, SURFACE2)
        _center(draw, _fmt(val), y0 + 32, fonts["num_md"], TEXT, x0, x0 + cell_w)
        _center(draw, lbl, y0 + 68, fonts["tiny"], MUTED, x0, x0 + cell_w)

    out = io.BytesIO()
    # high quality PNG
    img.save(out, format="PNG", optimize=False, compress_level=3)
    data = out.getvalue()
    logger.info("stats image generated: %s bytes, size=%sx%s, avatar=%s",
                len(data), W, H, bool(avatar_bytes))
    return data
