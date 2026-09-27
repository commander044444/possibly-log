"""Inline keyboards for python-bale-bot 2.5.0 (add + row API)."""
from __future__ import annotations

from typing import List, Optional

from bale import InlineKeyboardMarkup, InlineKeyboardButton

import config


def _markup_from_rows(rows: List[List[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    """Build InlineKeyboardMarkup using official .add(..., row=) API (1-based rows)."""
    mk = InlineKeyboardMarkup()
    for i, row in enumerate(rows, start=1):
        for btn in row:
            mk.add(btn, row=i)
    return mk


def main_menu() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="➕ اضافه کردن کانال", callback_data="ch:add"),
            InlineKeyboardButton(text="➖ حذف کانال", callback_data="ch:remove"),
        ],
        [
            InlineKeyboardButton(text="📊 آمار کانال من", callback_data="stats:menu"),
            InlineKeyboardButton(text="⚙️ تنظیمات کانال", callback_data="ch:manage"),
        ],
        [
            InlineKeyboardButton(text="📰 دسته‌بندی اخبار", callback_data="cat:menu"),
            InlineKeyboardButton(text="⏱ تنظیم زمان ارسال", callback_data="ch:interval_menu"),
        ],
        [
            InlineKeyboardButton(text="▶️ شروع فعالیت", callback_data="news:start"),
            InlineKeyboardButton(text="⏸ توقف فعالیت", callback_data="news:stop"),
        ],
        [
            InlineKeyboardButton(text="👑 خرید VIP", callback_data="pay:menu"),
            InlineKeyboardButton(text="📅 وضعیت اشتراک", callback_data="sub:status"),
        ],
        [
            InlineKeyboardButton(text="🔑 وارد کردن لایسنس", callback_data="lic:enter"),
        ],
        [
            InlineKeyboardButton(text="🛠 پیگیری مشکلات", callback_data="support:menu"),
            InlineKeyboardButton(text="❓ سوالات متداول", callback_data="faq:menu"),
        ],
        [
            InlineKeyboardButton(text="ℹ️ درباره ما", callback_data="about"),
        ],
    ]
    return _markup_from_rows(rows)


def back_main() -> InlineKeyboardMarkup:
    return _markup_from_rows([
        [InlineKeyboardButton(text="🔙 بازگشت به منو", callback_data="menu:main")]
    ])


def vip_upgrade_kb() -> InlineKeyboardMarkup:
    return _markup_from_rows([
        [InlineKeyboardButton(text="👑 خرید VIP", callback_data="pay:menu")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu:main")],
    ])


subscription_gate_kb = vip_upgrade_kb
vip_gate_kb = vip_upgrade_kb


def plans_from_db_kb(plans: list, method: str) -> InlineKeyboardMarkup:
    rows = []
    for p in plans:
        rows.append([
            InlineKeyboardButton(
                text=f"{p['name']} — {p['price']:,} تومان",
                callback_data=f"pay:plan:{method}:{p['id']}",
            )
        ])
    rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="pay:menu")])
    return _markup_from_rows(rows)


def pay_method_kb() -> InlineKeyboardMarkup:
    return _markup_from_rows([
        [InlineKeyboardButton(text="🎁 پاکت هدیه", callback_data="pay:method:gift")],
        [InlineKeyboardButton(text="💳 کارت به کارت", callback_data="pay:method:card")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu:main")],
    ])


def confirm_kb(yes_data: str, no_data: str = "menu:main") -> InlineKeyboardMarkup:
    return _markup_from_rows([
        [
            InlineKeyboardButton(text="✅ بله", callback_data=yes_data),
            InlineKeyboardButton(text="❌ لغو", callback_data=no_data),
        ]
    ])


def admin_payment_kb(payment_id: int) -> InlineKeyboardMarkup:
    return _markup_from_rows([
        [
            InlineKeyboardButton(text="✅ تایید", callback_data=f"admin:pay:approve:{payment_id}"),
            InlineKeyboardButton(text="❌ رد", callback_data=f"admin:pay:reject:{payment_id}"),
        ],
        [
            InlineKeyboardButton(text="💬 پیام به کاربر", callback_data=f"admin:pay:msg:{payment_id}"),
        ],
    ])


def admin_receipt_kb(payment_id: int) -> InlineKeyboardMarkup:
    return _markup_from_rows([
        [
            InlineKeyboardButton(text="✅ تایید پرداخت", callback_data=f"admin:rcpt:approve:{payment_id}"),
            InlineKeyboardButton(text="❌ رد پرداخت", callback_data=f"admin:rcpt:reject:{payment_id}"),
        ],
        [
            InlineKeyboardButton(text="💬 پیام به کاربر", callback_data=f"admin:pay:msg:{payment_id}"),
        ],
    ])


def cancel_kb(data: str = "menu:main") -> InlineKeyboardMarkup:
    return _markup_from_rows([
        [InlineKeyboardButton(text="❌ لغو", callback_data=data)]
    ])


def intervals_kb(intervals: List[int]) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for mins in intervals:
        if mins >= 60:
            label = f"⏱ {mins // 60} ساعت"
        else:
            label = f"⏱ {mins} دقیقه"
        row.append(InlineKeyboardButton(
            text=label,
            callback_data=f"ch:interval:{mins}",
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="ch:manage")])
    return _markup_from_rows(rows)


def categories_kb(selected: Optional[List[str]] = None, allowed_keys: Optional[List[str]] = None) -> InlineKeyboardMarkup:
    selected = selected or []
    keys = allowed_keys or list(config.CATEGORIES.keys())
    rows = []
    row = []
    for key in keys:
        title = config.CATEGORIES.get(key, key)
        mark = "✅ " if key in selected else ""
        row.append(InlineKeyboardButton(
            text=f"{mark}{title}",
            callback_data=f"cat:toggle:{key}",
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton(text="✅ همه", callback_data="cat:all"),
        InlineKeyboardButton(text="🗑 پاک کردن", callback_data="cat:clear"),
    ])
    rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu:main")])
    return _markup_from_rows(rows)


def support_menu_kb() -> InlineKeyboardMarkup:
    items = [
        ("🔑 مشکلات لایسنس", "support:cat:license"),
        ("💳 مشکلات پرداخت", "support:cat:payment"),
        ("📺 مشکلات کانال", "support:cat:channel"),
        ("📰 مشکلات اخبار", "support:cat:news"),
        ("📊 مشکلات آمار", "support:cat:stats"),
        ("⚙️ مشکلات تنظیمات", "support:cat:settings"),
        ("🚨 گزارش باگ", "support:cat:bug"),
        ("📢 شکایت", "support:cat:complaint"),
        ("💬 سایر موارد", "support:cat:other"),
    ]
    rows = [[InlineKeyboardButton(text=t, callback_data=d)] for t, d in items]
    rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu:main")])
    return _markup_from_rows(rows)


def faq_menu_kb() -> InlineKeyboardMarkup:
    items = [
        ("🆓 FREE", "faq:free"),
        ("👑 VIP", "faq:vip"),
        ("💰 پرداخت", "faq:pay"),
        ("🔑 لایسنس", "faq:license"),
        ("📺 کانال", "faq:channel"),
        ("📰 اخبار", "faq:news"),
        ("📊 آمار", "faq:stats"),
        ("🛠 پشتیبانی", "faq:support"),
    ]
    rows = [[InlineKeyboardButton(text=t, callback_data=d)] for t, d in items]
    rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu:main")])
    return _markup_from_rows(rows)


def admin_panel_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="👥 کاربران", callback_data="admin:users")],
        [InlineKeyboardButton(text="🛡 ادمین‌ها", callback_data="admin:admins")],
        [InlineKeyboardButton(text="📺 کانال‌ها", callback_data="admin:channels")],
        [InlineKeyboardButton(text="💳 پلن‌ها و قیمت‌ها", callback_data="admin:plans")],
        [InlineKeyboardButton(text="💳 شماره کارت", callback_data="admin:card")],
        [InlineKeyboardButton(text="💰 پرداخت‌ها", callback_data="admin:payments")],
        [InlineKeyboardButton(text="🔑 لایسنس‌ها", callback_data="admin:licenses")],
        [InlineKeyboardButton(text="📢 Broadcast", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="📊 آمار سیستم", callback_data="admin:stats")],
        [InlineKeyboardButton(text="📰 منابع خبری", callback_data="admin:sources")],
        [InlineKeyboardButton(text="🎫 تیکت‌ها", callback_data="admin:tickets")],
        [InlineKeyboardButton(text="❤️ Health", callback_data="admin:health")],
        [InlineKeyboardButton(text="⚙️ تنظیمات", callback_data="admin:settings")],
    ]
    return _markup_from_rows(rows)


def about_kb() -> InlineKeyboardMarkup:
    return _markup_from_rows([
        [InlineKeyboardButton(text="👤 @commander04", url="https://ble.ir/commander04")],
        [InlineKeyboardButton(text="⚔️ DARKKNIGHT STUDIO", url="https://ble.ir/darkknight_studio")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu:main")],
    ])
