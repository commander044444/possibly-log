"""
Channel stats image — NO avatar, maximum readable bold type.
Real data only. Canvas sized for huge mobile-friendly numbers.
"""
from __future__ import annotations

import io
import logging
import os
from datetime import date, timedelta
from typing import Optional, List, Tuple, Any

import database as db

logger = logging.getLogger(__name__)

# Tall portrait so huge fonts still fit
W, H = 1080, 1920

BG = (8, 10, 16)
SURFACE = (22, 26, 40)
SURFACE2 = (32, 38, 56)
ACCENT = (96, 165, 250)
GREEN = (52, 211, 153)
ROSE = (251, 113, 133)
AMBER = (251, 191, 36)
TEXT = (255, 255, 255)
MUTED = (160, 170, 190)


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

    def f(size, use_bold=True):
        path = bold if use_bold else reg
        try:
            if path:
                return ImageFont.truetype(path, size)
        except Exception:
            pass
        return ImageFont.load_default()

    # Extreme sizes for mobile (as large as practical on one screen)
    return {
        "title": f(72, True),
        "uname": f(48, True),
        "num_hero": f(110, True),
        "num": f(90, True),
        "num_md": f(70, True),
        "label": f(36, True),
        "section": f(42, True),
        "tiny": f(30, True),
    }


def _round(draw, box, r, fill):
    draw.rounded_rectangle(box, radius=r, fill=fill)


def _center(draw, text, cy, font, fill, x0, x1):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text((x0 + (x1 - x0 - tw) // 2, cy - th // 2), text, font=font, fill=fill)


def _chart(series: List[Tuple[Any, int]], w=1000, h=360):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image
    import numpy as np

    fig, ax = plt.subplots(figsize=(w / 100, h / 100), dpi=140)
    fig.patch.set_facecolor("#161a28")
    ax.set_facecolor("#161a28")

    today = date.today()
    lookup = {d: m for d, m in series}
    dates = [today - timedelta(days=i) for i in range(29, -1, -1)]
    ys = [lookup.get(d, 0) for d in dates]
    xs = np.arange(30)

    if any(ys):
        ax.fill_between(xs, ys, color="#60A5FA", alpha=0.25)
        ax.plot(xs, ys, color="#60A5FA", linewidth=5.0, solid_capstyle="round")
        peak = int(np.argmax(ys))
        ax.scatter([peak], [ys[peak]], color="#FB7185", s=120, zorder=5)
        ax.set_xlim(-0.5, 29.5)
        ax.set_ylim(0, max(max(ys) * 1.3, 1))
        ticks = [0, 7, 14, 21, 29]
        ax.set_xticks(ticks)
        ax.set_xticklabels(
            [dates[i].strftime("%m/%d") for i in ticks],
            color="#A0AABF", fontsize=16, fontweight="bold",
        )
        ax.tick_params(axis="y", colors="#A0AABF", labelsize=16)
        for s in ax.spines.values():
            s.set_color("#3A4158")
            s.set_linewidth(1.5)
        ax.grid(axis="y", color="#3A4158", linestyle="--", linewidth=1.0)
    else:
        ax.text(0.5, 0.5, "No data yet", ha="center", va="center",
                color="#A0AABF", fontsize=28, fontweight="bold")
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)

    fig.tight_layout(pad=0.5)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, facecolor=fig.get_facecolor(),
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
    avatar_bytes: Optional[bytes] = None,  # ignored — avatar removed by design
    channel_id: Optional[int] = None,
) -> bytes:
    """Huge-type dashboard. Avatar intentionally not rendered."""
    from PIL import Image, ImageDraw

    fonts = _fonts()
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    pad = 36
    y = 40

    # ── TITLE ONLY (no avatar) ─────────────────────────
    _round(draw, (pad, y, W - pad, y + 200), 28, SURFACE)
    title = (channel_title or "Channel")[:26]
    _center(draw, title, y + 70, fonts["title"], TEXT, pad, W - pad)
    if channel_username:
        _center(draw, f"@{channel_username}", y + 135, fonts["uname"], ACCENT, pad, W - pad)
    meta = stats.get("report_date", "—")
    if channel_id is not None:
        meta = f"{meta}  ·  ID {channel_id}"
    _center(draw, meta, y + 175, fonts["tiny"], MUTED, pad, W - pad)
    y += 220

    # ── MEMBERS HERO ───────────────────────────────────
    mem = members if members is not None else stats.get("members_now")
    g7 = stats.get("growth_7d")
    g30 = stats.get("growth_30d")

    def gtxt(v):
        if v is None:
            return "—"
        return f"+{v}" if v > 0 else str(v)

    _round(draw, (pad, y, W - pad, y + 200), 28, SURFACE)
    _center(draw, _fmt(mem), y + 80, fonts["num_hero"], TEXT if mem is not None else MUTED, pad, W - pad)
    _center(draw, "MEMBERS", y + 160, fonts["label"], MUTED, pad, W - pad)
    y += 220

    # growth row
    gap = 16
    cw = (W - 2 * pad - gap) // 2
    for i, (val, lbl) in enumerate([(gtxt(g7), "7d GROWTH"), (gtxt(g30), "30d GROWTH")]):
        x0 = pad + i * (cw + gap)
        _round(draw, (x0, y, x0 + cw, y + 160), 24, SURFACE)
        _center(draw, val, y + 65, fonts["num"], TEXT if val != "—" else MUTED, x0, x0 + cw)
        _center(draw, lbl, y + 125, fonts["label"], MUTED, x0, x0 + cw)
    y += 180

    # ── MESSAGE KPIs ───────────────────────────────────
    kpis = [
        (_fmt(stats.get("today_messages", 0)), "TODAY", ACCENT),
        (_fmt(stats.get("week_messages", 0)), "7 DAYS", GREEN),
        (_fmt(stats.get("month_messages", 0)), "30 DAYS", ROSE),
        (_fmt(stats.get("total_messages", 0)), "TOTAL", AMBER),
    ]
    cw = (W - 2 * pad - 3 * gap) // 4
    for i, (val, lbl, color) in enumerate(kpis):
        x0 = pad + i * (cw + gap)
        _round(draw, (x0, y, x0 + cw, y + 180), 24, SURFACE)
        draw.rounded_rectangle((x0 + 14, y + 12, x0 + cw - 14, y + 22), radius=4, fill=color)
        _center(draw, val, y + 85, fonts["num_md"], TEXT, x0, x0 + cw)
        _center(draw, lbl, y + 145, fonts["tiny"], MUTED, x0, x0 + cw)
    y += 200

    # ── CHART ──────────────────────────────────────────
    ch = 400
    _round(draw, (pad, y, W - pad, y + ch), 28, SURFACE)
    draw.text((pad + 28, y + 20), "ACTIVITY · 30 DAYS", font=fonts["section"], fill=TEXT)
    try:
        chart = _chart(stats.get("daily_series") or [])
        chart = chart.resize((W - 2 * pad - 40, 320), Image.Resampling.LANCZOS)
        img.paste(chart, (pad + 20, y + 70), chart)
    except Exception:
        logger.exception("chart")
        _center(draw, "Chart unavailable", y + ch // 2, fonts["label"], MUTED, pad, W - pad)
    y += ch + 16

    # ── CONTENT (compact but big numbers) ──────────────
    remain = H - y - 30
    if remain > 220:
        _round(draw, (pad, y, W - pad, y + remain), 28, SURFACE)
        draw.text((pad + 28, y + 16), "CONTENT · 30 DAYS", font=fonts["section"], fill=TEXT)
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
        cell_w = (W - 2 * pad - 40) // 4
        for i, (lbl, val) in enumerate(items):
            col, rowi = i % 4, i // 4
            x0 = pad + 20 + col * cell_w
            y0 = y + 70 + rowi * 100
            _round(draw, (x0 + 4, y0, x0 + cell_w - 8, y0 + 90), 18, SURFACE2)
            _center(draw, _fmt(val), y0 + 35, fonts["num_md"], TEXT, x0, x0 + cell_w)
            _center(draw, lbl, y0 + 72, fonts["tiny"], MUTED, x0, x0 + cell_w)

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=False, compress_level=2)
    data = out.getvalue()
    logger.info("stats image %d bytes %dx%d (no avatar)", len(data), W, H)
    return data
