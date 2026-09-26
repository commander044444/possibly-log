"""
Channel stats — 1080px wide, numbers auto-fit to nearly full card width.
Maximum practical size on mobile. No avatar. Real data only.
"""
from __future__ import annotations

import io
import logging
import os
from datetime import date, timedelta
from typing import Optional, List, Tuple, Any

import database as db

logger = logging.getLogger(__name__)

W, H = 1080, 2400  # tall so each block can be huge

BG = (6, 8, 14)
SURFACE = (20, 24, 36)
SURFACE2 = (30, 36, 52)
ACCENT = (96, 165, 250)
GREEN = (52, 211, 153)
ROSE = (251, 113, 133)
AMBER = (251, 191, 36)
TEXT = (255, 255, 255)
MUTED = (170, 180, 200)


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


def _bold_path():
    for p in (
        "/usr/share/fonts/SlidesCarnival/google/Cairo/static/Cairo-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ):
        if os.path.exists(p):
            return p
    return None


def _font(size: int):
    from PIL import ImageFont
    path = _bold_path()
    try:
        if path:
            return ImageFont.truetype(path, size)
    except Exception:
        pass
    return ImageFont.load_default()


def _fit_font(draw, text: str, max_width: int, max_size: int, min_size: int = 40):
    """Grow font until text nearly fills max_width (true max size on 1080)."""
    size = max_size
    while size >= min_size:
        font = _font(size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font, bbox[2] - bbox[0], bbox[3] - bbox[1]
        size -= 4
    font = _font(min_size)
    bbox = draw.textbbox((0, 0), text, font=font)
    return font, bbox[2] - bbox[0], bbox[3] - bbox[1]


def _center(draw, text, cy, font, fill, x0, x1):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text((x0 + (x1 - x0 - tw) // 2, cy - th // 2), text, font=font, fill=fill)


def _chart(series: List[Tuple[Any, int]], w=1000, h=400):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image
    import numpy as np

    fig, ax = plt.subplots(figsize=(w / 100, h / 100), dpi=150)
    fig.patch.set_facecolor("#141824")
    ax.set_facecolor("#141824")

    today = date.today()
    lookup = {d: m for d, m in series}
    dates = [today - timedelta(days=i) for i in range(29, -1, -1)]
    ys = [lookup.get(d, 0) for d in dates]
    xs = np.arange(30)

    if any(ys):
        ax.fill_between(xs, ys, color="#60A5FA", alpha=0.3)
        ax.plot(xs, ys, color="#60A5FA", linewidth=6.0, solid_capstyle="round")
        peak = int(np.argmax(ys))
        ax.scatter([peak], [ys[peak]], color="#FB7185", s=160, zorder=5)
        ax.set_xlim(-0.5, 29.5)
        ax.set_ylim(0, max(max(ys) * 1.3, 1))
        ticks = [0, 7, 14, 21, 29]
        ax.set_xticks(ticks)
        ax.set_xticklabels(
            [dates[i].strftime("%m/%d") for i in ticks],
            color="#AAB4C8", fontsize=18, fontweight="bold",
        )
        ax.tick_params(axis="y", colors="#AAB4C8", labelsize=18)
        for s in ax.spines.values():
            s.set_color("#3A4158")
            s.set_linewidth(2)
        ax.grid(axis="y", color="#3A4158", linestyle="--", linewidth=1.2)
    else:
        ax.text(0.5, 0.5, "No data yet", ha="center", va="center",
                color="#AAB4C8", fontsize=32, fontweight="bold")
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)

    fig.tight_layout(pad=0.4)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, facecolor=fig.get_facecolor(),
                edgecolor="none", bbox_inches="tight", pad_inches=0.12)
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

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    pad = 28
    y = 28
    inner_w = W - 2 * pad - 48  # max text width inside cards

    # ── CHANNEL NAME (fills width) ─────────────────────
    hh = 220
    draw.rounded_rectangle((pad, y, W - pad, y + hh), radius=28, fill=SURFACE)
    title = (channel_title or "Channel")[:24]
    font, tw, th = _fit_font(draw, title, inner_w, max_size=120, min_size=48)
    _center(draw, title, y + 70, font, TEXT, pad, W - pad)

    if channel_username:
        un = f"@{channel_username}"[:28]
        font2, _, _ = _fit_font(draw, un, inner_w, max_size=64, min_size=36)
        _center(draw, un, y + 140, font2, ACCENT, pad, W - pad)

    meta = stats.get("report_date", "—")
    if channel_id is not None:
        meta = f"{meta}  ·  {channel_id}"
    _center(draw, meta, y + 190, _font(28), MUTED, pad, W - pad)
    y += hh + 20

    # ── MEMBERS (hero — largest number on image) ───────
    mem = members if members is not None else stats.get("members_now")
    mem_s = _fmt(mem)
    hh = 280
    draw.rounded_rectangle((pad, y, W - pad, y + hh), radius=28, fill=SURFACE)
    font, _, _ = _fit_font(draw, mem_s, inner_w, max_size=220, min_size=80)
    _center(draw, mem_s, y + 110, font, TEXT if mem is not None else MUTED, pad, W - pad)
    _center(draw, "MEMBERS", y + 230, _font(40), MUTED, pad, W - pad)
    y += hh + 18

    # ── GROWTH ─────────────────────────────────────────
    def gtxt(v):
        if v is None:
            return "—"
        return f"+{v}" if v > 0 else str(v)

    g7, g30 = gtxt(stats.get("growth_7d")), gtxt(stats.get("growth_30d"))
    gap = 14
    cw = (W - 2 * pad - gap) // 2
    for i, (val, lbl) in enumerate([(g7, "7d GROWTH"), (g30, "30d GROWTH")]):
        x0 = pad + i * (cw + gap)
        draw.rounded_rectangle((x0, y, x0 + cw, y + 220), radius=24, fill=SURFACE)
        font, _, _ = _fit_font(draw, val, cw - 40, max_size=120, min_size=50)
        _center(draw, val, y + 90, font, TEXT if val != "—" else MUTED, x0, x0 + cw)
        _center(draw, lbl, y + 180, _font(32), MUTED, x0, x0 + cw)
    y += 240

    # ── 4 MESSAGE STATS (2×2 grid, huge) ───────────────
    kpis = [
        (_fmt(stats.get("today_messages", 0)), "TODAY", ACCENT),
        (_fmt(stats.get("week_messages", 0)), "7 DAYS", GREEN),
        (_fmt(stats.get("month_messages", 0)), "30 DAYS", ROSE),
        (_fmt(stats.get("total_messages", 0)), "TOTAL", AMBER),
    ]
    cw = (W - 2 * pad - gap) // 2
    ch = 230
    for i, (val, lbl, color) in enumerate(kpis):
        col, row = i % 2, i // 2
        x0 = pad + col * (cw + gap)
        y0 = y + row * (ch + gap)
        draw.rounded_rectangle((x0, y0, x0 + cw, y0 + ch), radius=24, fill=SURFACE)
        draw.rounded_rectangle((x0 + 20, y0 + 14, x0 + cw - 20, y0 + 26), radius=4, fill=color)
        font, _, _ = _fit_font(draw, val, cw - 40, max_size=130, min_size=50)
        _center(draw, val, y0 + 110, font, TEXT, x0, x0 + cw)
        _center(draw, lbl, y0 + 190, _font(34), MUTED, x0, x0 + cw)
    y += 2 * (ch + gap) + 6

    # ── CHART ──────────────────────────────────────────
    chh = 420
    if y + chh < H - 40:
        draw.rounded_rectangle((pad, y, W - pad, y + chh), radius=24, fill=SURFACE)
        draw.text((pad + 24, y + 18), "ACTIVITY · 30 DAYS", font=_font(36), fill=TEXT)
        try:
            chart = _chart(stats.get("daily_series") or [])
            chart = chart.resize((W - 2 * pad - 36, 340), Image.Resampling.LANCZOS)
            img.paste(chart, (pad + 18, y + 65), chart)
        except Exception:
            logger.exception("chart")
            _center(draw, "Chart unavailable", y + chh // 2, _font(36), MUTED, pad, W - pad)

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=False, compress_level=2)
    data = out.getvalue()
    logger.info("stats image %d bytes %dx%d fit-font max", len(data), W, H)
    return data
