"""
Channel statistics image generation (Pillow + matplotlib).
Always free for channel owners.
"""
from __future__ import annotations

import io
import logging
from datetime import date, timedelta
from typing import Optional

import database as db

logger = logging.getLogger(__name__)


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
    month = daily

    def sum_col(rows, col):
        return sum(r[col] or 0 for r in rows)

    return {
        "today_messages": (today_row["messages"] if today_row else 0),
        "week_messages": sum_col(week, "messages"),
        "month_messages": sum_col(month, "messages"),
        "photo": sum_col(month, "photo_count"),
        "video": sum_col(month, "video_count"),
        "gif": sum_col(month, "gif_count"),
        "voice": sum_col(month, "voice_count"),
        "audio": sum_col(month, "audio_count"),
        "sticker": sum_col(month, "sticker_count"),
        "file": sum_col(month, "file_count"),
        "text": sum_col(month, "text_count"),
        "daily_series": [(r["date"], r["messages"]) for r in daily],
    }


def render_stats_image(
    channel_title: str,
    channel_username: Optional[str],
    stats: dict,
) -> bytes:
    """
    Generate a professional stats card.
    Returns PNG bytes.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from PIL import Image, ImageDraw, ImageFont
        import numpy as np
    except ImportError:
        # minimal fallback without viz libs
        return _fallback_text_image(channel_title, stats)

    # chart
    fig, ax = plt.subplots(figsize=(8, 2.5), dpi=100)
    series = stats.get("daily_series") or []
    if series:
        xs = [str(d)[-5:] for d, _ in series]
        ys = [m for _, m in series]
        ax.bar(xs, ys, color="#4C8BF5")
        ax.set_ylabel("پیام")
        ax.tick_params(axis="x", rotation=45, labelsize=7)
    else:
        ax.text(0.5, 0.5, "داده‌ای نیست", ha="center", va="center")
        ax.set_xticks([])
        ax.set_yticks([])
    ax.set_title("فعالیت ۳۰ روز اخیر")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="#1a1a2e")
    plt.close(fig)
    buf.seek(0)
    chart = Image.open(buf).convert("RGBA")

    # card
    W, H = 800, 900
    img = Image.new("RGB", (W, H), "#16213e")
    draw = ImageDraw.Draw(img)
    try:
        font_lg = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
        font_md = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
    except Exception:
        font_lg = ImageFont.load_default()
        font_md = font_lg
        font_sm = font_lg

    y = 30
    draw.text((40, y), "📊 آمار کانال", fill="#e94560", font=font_lg)
    y += 50
    title = (channel_title or "کانال")[:40]
    draw.text((40, y), title, fill="#ffffff", font=font_md)
    y += 35
    if channel_username:
        draw.text((40, y), f"@{channel_username}", fill="#a0a0a0", font=font_sm)
        y += 30

    lines = [
        f"پیام‌های امروز: {stats['today_messages']}",
        f"پیام‌های هفته: {stats['week_messages']}",
        f"پیام‌های ماه: {stats['month_messages']}",
        f"متن: {stats['text']} | عکس: {stats['photo']} | ویدیو: {stats['video']}",
        f"GIF: {stats['gif']} | صوت: {stats['voice']} | صوت‌کلیپ: {stats['audio']}",
        f"استیکر: {stats['sticker']} | فایل: {stats['file']}",
    ]
    y += 20
    for line in lines:
        draw.text((40, y), line, fill="#eeeeee", font=font_sm)
        y += 28

    # paste chart
    chart = chart.resize((720, 220))
    img.paste(chart, (40, y + 20), chart if chart.mode == "RGBA" else None)

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _fallback_text_image(title: str, stats: dict) -> bytes:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (600, 400), "#222")
    d = ImageDraw.Draw(img)
    d.text((20, 20), f"Stats: {title}", fill="white")
    d.text((20, 60), f"Today: {stats.get('today_messages', 0)}", fill="white")
    d.text((20, 90), f"Week: {stats.get('week_messages', 0)}", fill="white")
    d.text((20, 120), f"Month: {stats.get('month_messages', 0)}", fill="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
