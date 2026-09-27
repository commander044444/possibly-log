"""Admin panel — full user management, payments, licenses. Only ADMIN_ID."""
from __future__ import annotations

import logging

from bale import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

import config
import database as db
import keyboards as kb
from services import payments as pay_svc
from services import subscription as sub_svc
from utils.helpers import is_admin, is_super_admin, resolve_user_ref, format_user_ref

logger = logging.getLogger(__name__)


def _admin_users_kb(users: list, page: int = 0, page_size: int = 10) -> InlineKeyboardMarkup:
    mk = InlineKeyboardMarkup()
    start = page * page_size
    chunk = users[start:start + page_size]
    for i, u in enumerate(chunk, start=1):
        uid = int(u["user_id"])
        uname = u.get("username")
        name = u.get("first_name") or u.get("display_name") or ""
        label = format_user_ref(uname, uid)
        if name:
            label = f"{label} · {name}"[:40]
        banned = "🚫 " if u.get("is_banned") else ""
        mk.add(
            InlineKeyboardButton(text=f"{banned}{label}", callback_data=f"admin:user:{uid}"),
            row=i,
        )
    row = len(chunk) + 1
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ قبل", callback_data=f"admin:users:p:{page-1}"))
    if start + page_size < len(users):
        nav.append(InlineKeyboardButton(text="بعد ▶️", callback_data=f"admin:users:p:{page+1}"))
    for b in nav:
        mk.add(b, row=row)
    mk.add(InlineKeyboardButton(text="🔙 پنل ادمین", callback_data="admin:panel"), row=row + 1)
    return mk


def _user_actions_kb(target_id: int) -> InlineKeyboardMarkup:
    mk = InlineKeyboardMarkup()
    mk.add(InlineKeyboardButton(text="🎁 هدیه VIP", callback_data=f"admin:ugift:{target_id}"), row=1)
    mk.add(InlineKeyboardButton(text="✅ فعال‌سازی اشتراک", callback_data=f"admin:uact:{target_id}"), row=2)
    mk.add(InlineKeyboardButton(text="⏹ قطع اشتراک", callback_data=f"admin:udeact:{target_id}"), row=3)
    mk.add(InlineKeyboardButton(text="🚫 بن", callback_data=f"admin:uban:{target_id}"), row=4)
    mk.add(InlineKeyboardButton(text="🟢 آنبن", callback_data=f"admin:uunban:{target_id}"), row=5)
    mk.add(InlineKeyboardButton(text="💬 پیام به کاربر", callback_data=f"admin:umsg:{target_id}"), row=6)
    mk.add(InlineKeyboardButton(text="📺 کانال‌های کاربر", callback_data=f"admin:uch:{target_id}"), row=7)
    mk.add(InlineKeyboardButton(text="🔙 لیست کاربران", callback_data="admin:users"), row=8)
    return mk


def _gift_plans_kb(target_id: int, plans: list) -> InlineKeyboardMarkup:
    mk = InlineKeyboardMarkup()
    for i, p in enumerate(plans, start=1):
        mk.add(
            InlineKeyboardButton(
                text=f"{p['name']} ({p['duration_days']}روز)",
                callback_data=f"admin:ugiftgo:{target_id}:{p['id']}",
            ),
            row=i,
        )
    mk.add(InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"admin:user:{target_id}"), row=len(plans) + 1)
    return mk


async def _user_detail_text(target_id: int) -> str:
    row = await db.fetchrow("SELECT * FROM users WHERE user_id = $1", target_id)
    if not row:
        return f"کاربر {target_id} در دیتابیس نیست."
    uref = format_user_ref(row.get("username"), target_id)
    tier = await sub_svc.get_access_tier(target_id)
    sub = await sub_svc.get_active_subscription(target_id)
    ch_count = await db.fetchval(
        "SELECT COUNT(*) FROM channels WHERE owner_user_id = $1 AND status != 'removed'",
        target_id,
    )
    banned = "بله 🚫" if row.get("is_banned") else "خیر"
    lines = [
        "👤 جزئیات کاربر\n",
        f"شناسه نمایشی: {uref}",
        f"نام: {row.get('first_name') or '—'} {row.get('last_name') or ''}".strip(),
        f"وضعیت بن: {banned}",
        f"سطح: {tier}",
        f"کانال‌ها: {ch_count}",
    ]
    if sub:
        lines.append(f"پلن: {sub.get('plan_name') or sub.get('plan_key')}")
        lines.append(f"پایان اشتراک: {sub.get('expires_at')}")
    else:
        lines.append("اشتراک فعال: ندارد")
    return "\n".join(lines)


async def handle_admin_callback(callback: CallbackQuery, bot) -> None:
    data = (callback.data or "").strip()
    user = callback.from_user
    if not user or not await is_admin(int(user.user_id)):
        return
    msg = callback.message
    uid = int(user.user_id)

    if data in ("admin:panel", "admin:menu"):
        await msg.reply("🛠 پنل مدیریت", components=kb.admin_panel_kb())
        return

    # ── users list ──────────────────────────────────────
    if data == "admin:users" or data.startswith("admin:users:p:"):
        page = 0
        if data.startswith("admin:users:p:"):
            try:
                page = int(data.split(":")[-1])
            except ValueError:
                page = 0
        users = await db.fetch(
            """
            SELECT user_id, username, first_name, last_name, display_name, is_banned, last_seen
            FROM users
            ORDER BY last_seen DESC NULLS LAST, user_id DESC
            LIMIT 200
            """
        )
        users = [dict(u) for u in users]
        if not users:
            await msg.reply("کاربری ثبت نشده.", components=kb.admin_panel_kb())
            return
        total = len(users)
        await msg.reply(
            f"👥 کاربران (نمایش تا ۲۰۰ نفر | مجموع این لیست: {total})\n"
            "روی هر کاربر بزنید:",
            components=_admin_users_kb(users, page=page),
        )
        return

    if data.startswith("admin:user:"):
        target = int(data.split(":")[-1])
        text = await _user_detail_text(target)
        await msg.reply(text, components=_user_actions_kb(target))
        return

    if data.startswith("admin:uban:"):
        target = int(data.split(":")[-1])
        await sub_svc.set_banned(target, True)
        # stop their channels
        await db.execute(
            "UPDATE channels SET is_active = FALSE WHERE owner_user_id = $1",
            target,
        )
        try:
            await bot.send_message(chat_id=target, text="🚫 حساب شما توسط مدیریت مسدود شد.")
        except Exception:
            pass
        await msg.reply(f"کاربر بن شد.\n{await resolve_user_ref(target)}", components=_user_actions_kb(target))
        return

    if data.startswith("admin:uunban:"):
        target = int(data.split(":")[-1])
        await sub_svc.set_banned(target, False)
        try:
            await bot.send_message(chat_id=target, text="🟢 مسدودیت حساب شما برداشته شد.")
        except Exception:
            pass
        await msg.reply(f"آنبن شد.\n{await resolve_user_ref(target)}", components=_user_actions_kb(target))
        return

    if data.startswith("admin:udeact:"):
        target = int(data.split(":")[-1])
        await sub_svc.deactivate_subscription(target)
        await db.execute(
            "UPDATE channels SET is_active = FALSE, status = 'registered' WHERE owner_user_id = $1",
            target,
        )
        try:
            await bot.send_message(chat_id=target, text="⏹ اشتراک VIP شما توسط مدیریت قطع شد.")
        except Exception:
            pass
        await msg.reply("اشتراک قطع شد.", components=_user_actions_kb(target))
        return

    if data.startswith("admin:uact:") or data.startswith("admin:ugift:"):
        # show plan picker (same UI)
        target = int(data.split(":")[-1])
        plans = await db.fetch(
            "SELECT * FROM plans WHERE enabled = TRUE ORDER BY price ASC"
        )
        if not plans:
            await msg.reply("پلن فعالی نیست.", components=_user_actions_kb(target))
            return
        await msg.reply(
            f"پلن هدیه برای {await resolve_user_ref(target)} را انتخاب کنید:",
            components=_gift_plans_kb(target, [dict(p) for p in plans]),
        )
        return

    if data.startswith("admin:ugiftgo:"):
        parts = data.split(":")
        target = int(parts[2])
        plan_id = int(parts[3])
        ok, info = await sub_svc.gift_plan_to_user(target, plan_id)
        if ok:
            try:
                await bot.send_message(
                    chat_id=target,
                    text=f"🎁 {info}\nاز بخش وضعیت اشتراک می‌توانید ببینید.",
                )
            except Exception:
                pass
        await msg.reply(info if ok else f"❌ {info}", components=_user_actions_kb(target))
        return

    if data.startswith("admin:uch:"):
        target = int(data.split(":")[-1])
        rows = await db.fetch(
            """
            SELECT channel_id, channel_title, channel_username, is_active, status, news_interval
            FROM channels WHERE owner_user_id = $1 AND status != 'removed'
            ORDER BY created_at DESC NULLS LAST
            """,
            target,
        )
        if not rows:
            await msg.reply("کانالی ندارد.", components=_user_actions_kb(target))
            return
        lines = [f"📺 کانال‌های {await resolve_user_ref(target)}\n"]
        for r in rows:
            st = "🟢" if r["is_active"] else "⚪"
            lines.append(
                f"{st} {r['channel_title'] or r['channel_id']} "
                f"(@{r['channel_username'] or '—'}) iv={r['news_interval']}m"
            )
        await msg.reply("\n".join(lines), components=_user_actions_kb(target))
        return

    if data.startswith("admin:umsg:"):
        target = int(data.split(":")[-1])
        from handlers.user import set_state
        await set_state(uid, "admin_msg_user", {"target_id": target})
        await msg.reply(
            f"پیام خود را برای {await resolve_user_ref(target)} بفرستید:\n(یا /cancel)",
            components=kb.cancel_kb("admin:users"),
        )
        return

    # ── legacy ban/unban entry points → redirect to users list
    if data in ("admin:ban", "admin:unban"):
        await msg.reply(
            "از «👥 کاربران» کاربر را انتخاب کنید و بن/آنبن بزنید.",
            components=kb.admin_panel_kb(),
        )
        return

    if data == "admin:stats":
        users = await db.fetchval("SELECT COUNT(*) FROM users")
        banned = await db.fetchval("SELECT COUNT(*) FROM users WHERE is_banned")
        paid = await db.fetchval(
            "SELECT COUNT(*) FROM subscriptions WHERE status = 'active' AND expires_at > NOW()"
        )
        channels = await db.fetchval("SELECT COUNT(*) FROM channels WHERE status != 'removed'")
        active_ch = await db.fetchval("SELECT COUNT(*) FROM channels WHERE is_active")
        pending_pay = await db.fetchval(
            "SELECT COUNT(*) FROM payment_requests WHERE status IN ('pending','under_review','awaiting_receipt')"
        )
        news_today = await db.fetchval(
            "SELECT COUNT(*) FROM news_items WHERE fetched_at::date = CURRENT_DATE"
        )
        pub_today = await db.fetchval(
            "SELECT COUNT(*) FROM published_news WHERE published_at::date = CURRENT_DATE"
        )
        await msg.reply(
            "📊 آمار سیستم\n\n"
            f"کاربران: {users}\nبن‌شده: {banned}\nVIP فعال: {paid}\n"
            f"کانال‌ها: {channels} (فعال: {active_ch})\n"
            f"پرداخت باز: {pending_pay}\nاخبار امروز: {news_today}\nانتشار امروز: {pub_today}",
            components=kb.admin_panel_kb(),
        )
        return

    if data == "admin:health":
        try:
            await db.fetchval("SELECT 1")
            db_ok = True
        except Exception:
            db_ok = False
        sources = await db.fetch(
            "SELECT name, health_status FROM news_sources WHERE enabled"
        )
        lines = [f"{'🟢' if db_ok else '🔴'} Database (POSTGRESQL_URL)"]
        lines.append("🟢 Bot")
        lines.append("🟢 Scheduler")
        for s in sources:
            mark = "🟢" if s["health_status"] == "healthy" else "🟡"
            lines.append(f"{mark} Source {s['name']}")
        await msg.reply("❤️ Health\n\n" + "\n".join(lines), components=kb.admin_panel_kb())
        return

    if data == "admin:plans":
        plans = await db.fetch("SELECT * FROM plans ORDER BY id")
        if not plans:
            await msg.reply("پلنی نیست.", components=kb.admin_panel_kb())
            return
        from bale import InlineKeyboardMarkup, InlineKeyboardButton
        mk = InlineKeyboardMarkup()
        lines = ["💳 پلن‌ها و قیمت‌ها\n"]
        for i, pl in enumerate(plans, start=1):
            st = "🟢" if pl["enabled"] else "🔴"
            lines.append(
                f"{st} #{pl['id']} {pl['name']}\n"
                f"   💰 {pl['price']:,} تومان | ⏱ {pl['duration_days']} روز"
            )
            mk.add(
                InlineKeyboardButton(
                    text=f"💰 قیمت #{pl['id']}",
                    callback_data=f"admin:plan:price:{pl['id']}",
                ),
                row=i,
            )
            mk.add(
                InlineKeyboardButton(
                    text=("🔴 خاموش" if pl["enabled"] else "🟢 روشن") + f" #{pl['id']}",
                    callback_data=f"admin:plan:toggle:{pl['id']}",
                ),
                row=i,
            )
        mk.add(InlineKeyboardButton(text="🔙 پنل", callback_data="admin:panel"), row=len(plans) + 1)
        await msg.reply("\n".join(lines), components=mk)
        return

    if data.startswith("admin:plan:price:"):
        plan_id = int(data.split(":")[-1])
        plan = await db.fetchrow("SELECT * FROM plans WHERE id = $1", plan_id)
        if not plan:
            await msg.reply("پلن یافت نشد.")
            return
        from handlers.user import set_state
        await set_state(uid, "admin_set_plan_price", {"plan_id": plan_id})
        await msg.reply(
            f"قیمت جدید «{plan['name']}» را به تومان بفرستید\n"
            f"(فعلی: {plan['price']:,})\n/cancel برای لغو"
        )
        return

    if data.startswith("admin:plan:toggle:"):
        plan_id = int(data.split(":")[-1])
        await db.execute(
            "UPDATE plans SET enabled = NOT enabled WHERE id = $1",
            plan_id,
        )
        row = await db.fetchrow("SELECT name, enabled, price FROM plans WHERE id = $1", plan_id)
        st = "فعال" if row and row["enabled"] else "غیرفعال"
        await msg.reply(
            f"پلن «{row['name']}» الان {st} است.\nقیمت: {row['price']:,}",
            components=kb.admin_panel_kb(),
        )
        return

    if data == "admin:payments":
        rows = await db.fetch(
            """
            SELECT * FROM payment_requests
            WHERE status IN ('pending','awaiting_receipt','under_review')
            ORDER BY id DESC LIMIT 20
            """
        )
        if not rows:
            await msg.reply("پرداخت معلقی نیست.", components=kb.admin_panel_kb())
            return
        for r in rows:
            uref = await resolve_user_ref(r["user_id"])
            await bot.send_message(
                chat_id=uid,
                text=(
                    f"#{r['id']} | {r['method']} | {r['status']}\n"
                    f"کاربر: {uref}\n"
                    f"پلن: {r['plan_name'] or r['plan_key']} "
                    f"مبلغ: {r['amount']:,}"
                ),
                components=kb.admin_payment_kb(r["id"]),
            )
        return

    if data.startswith("admin:pay:approve:"):
        pid = int(data.split(":")[-1])
        pay = await pay_svc.get_payment(pid)
        if not pay:
            await msg.reply("یافت نشد.")
            return
        if pay["method"] == "gift":
            ok, err = await pay_svc.transition_payment(pid, "approved")
            if not ok:
                await msg.reply(err)
                return
            code = await pay_svc.create_license_for_payment(
                pid, pay["user_id"], pay["plan_key"], pay.get("plan_id")
            )
            if code:
                await bot.send_message(
                    chat_id=pay["user_id"],
                    text=(
                        "پرداخت شما تایید شد.\n\n"
                        "کد لایسنس را در «وارد کردن لایسنس» وارد کنید:\n\n"
                        f"{code}\n\n⚠️ در اختیار دیگران نگذارید."
                    ),
                )
                await msg.reply(f"لایسنس صادر شد #{pid}")
            else:
                await msg.reply("تایید شد اما صدور لایسنس ناموفق.")
            return

        ok, err = await pay_svc.transition_payment(pid, "awaiting_receipt")
        if not ok:
            await msg.reply(err)
            return
        card, holder = await pay_svc.get_card_settings()
        amount = pay["amount"]
        await bot.send_message(
            chat_id=pay["user_id"],
            text=(
                f"لطفاً مبلغ {amount:,} تومان را به کارت زیر واریز کنید.\n\n"
                f"شماره کارت:\n{card}\n"
                f"به نام: {holder}\n\n"
                f"{config.PAYMENT_REVIEW_NOTE}\n\n"
                "📸 اسکرین‌شات واریزی را همینجا ارسال کنید."
            ),
            components=kb.cancel_kb(),
        )
        from handlers.user import set_state
        await set_state(pay["user_id"], "await_receipt", {"payment_id": pid})
        await msg.reply(f"کارت برای کاربر ارسال شد #{pid}")
        return

    if data.startswith("admin:pay:reject:"):
        pid = int(data.split(":")[-1])
        pay = await pay_svc.get_payment(pid)
        ok, err = await pay_svc.transition_payment(pid, "rejected")
        if not ok:
            await msg.reply(err)
            return
        if pay:
            await bot.send_message(chat_id=pay["user_id"], text="درخواست پرداخت شما لغو شد.")
        await msg.reply(f"رد شد #{pid}")
        return

    if data.startswith("admin:rcpt:approve:"):
        pid = int(data.split(":")[-1])
        pay = await pay_svc.get_payment(pid)
        if not pay:
            await msg.reply("یافت نشد.")
            return
        ok, err = await pay_svc.transition_payment(pid, "approved")
        if not ok:
            await msg.reply(err)
            return
        code = await pay_svc.create_license_for_payment(
            pid, pay["user_id"], pay["plan_key"], pay.get("plan_id")
        )
        if code:
            await bot.send_message(
                chat_id=pay["user_id"],
                text=(
                    "پرداخت شما تایید شد.\n\n"
                    f"کد لایسنس:\n{code}\n\n"
                    "در بخش «وارد کردن لایسنس» وارد کنید."
                ),
            )
            await msg.reply(f"لایسنس صادر شد #{pid}")
        else:
            await msg.reply("تایید شد اما لایسنس صادر نشد.")
        return

    if data.startswith("admin:rcpt:reject:"):
        pid = int(data.split(":")[-1])
        pay = await pay_svc.get_payment(pid)
        ok, err = await pay_svc.transition_payment(pid, "rejected")
        if ok and pay:
            await bot.send_message(
                chat_id=pay["user_id"],
                text="رسید پرداخت شما توسط مدیریت تایید نشد.",
            )
        await msg.reply(f"رسید رد شد #{pid}" if ok else err)
        return

    if data == "admin:channels":
        rows = await db.fetch(
            """
            SELECT c.*, u.username AS owner_username
            FROM channels c
            LEFT JOIN users u ON u.user_id = c.owner_user_id
            WHERE c.status != 'removed'
            ORDER BY c.is_active DESC, c.channel_id DESC
            LIMIT 40
            """
        )
        if not rows:
            await msg.reply("کانالی نیست.", components=kb.admin_panel_kb())
            return
        lines = ["📺 کانال‌ها\n"]
        for r in rows:
            st = "🟢" if r["is_active"] else "⚪"
            owner = format_user_ref(r.get("owner_username"), r["owner_user_id"])
            lines.append(
                f"{st} {r['channel_title'] or r['channel_id']} | owner={owner}"
            )
        await msg.reply("\n".join(lines)[:3900], components=kb.admin_panel_kb())
        return

    if data == "admin:tickets":
        rows = await db.fetch(
            "SELECT * FROM tickets WHERE status = 'open' ORDER BY id DESC LIMIT 15"
        )
        if not rows:
            await msg.reply("تیکت بازی نیست.", components=kb.admin_panel_kb())
            return
        for t in rows:
            uref = await resolve_user_ref(t["user_id"])
            await bot.send_message(
                chat_id=uid,
                text=f"{t['ticket_code']} | {t['category']}\nکاربر: {uref}\n{t['message'][:500]}",
            )
        return

    if data == "admin:sources":
        rows = await db.fetch("SELECT * FROM news_sources ORDER BY priority")
        lines = [
            f"{'✅' if r['enabled'] else '⛔'} {r['name']} [{r['health_status']}] p={r['priority']}"
            for r in rows
        ]
        await msg.reply("منابع:\n" + ("\n".join(lines) or "خالی"), components=kb.admin_panel_kb())
        return

    if data == "admin:licenses":
        rows = await db.fetch(
            """
            SELECT id, user_id, plan_key, status, created_at, used_at
            FROM licenses ORDER BY id DESC LIMIT 20
            """
        )
        if not rows:
            await msg.reply("لایسنسی نیست.", components=kb.admin_panel_kb())
            return
        lines = ["🔑 آخرین لایسنس‌ها\n"]
        for r in rows:
            uref = await resolve_user_ref(r["user_id"]) if r["user_id"] else "—"
            lines.append(f"#{r['id']} {r['status']} | {uref} | {r['plan_key']}")
        await msg.reply("\n".join(lines), components=kb.admin_panel_kb())
        return

    if data == "admin:broadcast":
        from handlers.user import set_state
        await set_state(uid, "admin_broadcast", {})
        await msg.reply(
            "📢 متن Broadcast را بفرستید (به همه کاربران):\n/cancel برای لغو",
            components=kb.cancel_kb("admin:panel"),
        )
        return

    if data == "admin:card":
        card, holder = await pay_svc.get_card_settings()
        from bale import InlineKeyboardMarkup, InlineKeyboardButton
        mk = InlineKeyboardMarkup()
        mk.add(InlineKeyboardButton(text="✏️ تغییر شماره کارت", callback_data="admin:card:num"), row=1)
        mk.add(InlineKeyboardButton(text="✏️ تغییر نام صاحب کارت", callback_data="admin:card:holder"), row=2)
        mk.add(InlineKeyboardButton(text="🔙 پنل", callback_data="admin:panel"), row=3)
        await msg.reply(
            f"💳 تنظیمات کارت\n\nشماره:\n`{card}`\n\nبه نام:\n{holder}",
            components=mk,
        )
        return

    if data == "admin:card:num":
        from handlers.user import set_state
        await set_state(uid, "admin_set_card_num", {})
        await msg.reply("شماره کارت جدید را بفرستید (فقط عدد):\n/cancel برای لغو")
        return

    if data == "admin:card:holder":
        from handlers.user import set_state
        await set_state(uid, "admin_set_card_holder", {})
        await msg.reply("نام صاحب حساب را بفرستید:\n/cancel برای لغو")
        return

    if data == "admin:admins":
        rows = await db.fetch(
            "SELECT * FROM bot_admins ORDER BY role DESC, created_at ASC"
        )
        from bale import InlineKeyboardMarkup, InlineKeyboardButton
        mk = InlineKeyboardMarkup()
        lines = ["🛡 ادمین‌های ربات\n"]
        lines.append(f"⭐ Owner (config): {config.ADMIN_ID} @{config.ADMIN_USERNAME}\n")
        for i, r in enumerate(rows, start=1):
            uref = format_user_ref(r.get("username"), r["user_id"])
            role = r.get("role") or "admin"
            flags = []
            if not r.get("is_active", True):
                flags.append("غیرفعال")
            if r.get("is_banned"):
                flags.append("بن")
            flag_s = f" ({', '.join(flags)})" if flags else ""
            lines.append(f"• {uref} | {role}{flag_s}")
            mk.add(
                InlineKeyboardButton(
                    text=f"مدیریت {uref}"[:40],
                    callback_data=f"admin:adm:{r['user_id']}",
                ),
                row=i,
            )
        mk.add(InlineKeyboardButton(text="➕ افزودن ادمین", callback_data="admin:adm:add"), row=len(rows) + 1)
        mk.add(InlineKeyboardButton(text="🔙 پنل", callback_data="admin:panel"), row=len(rows) + 2)
        await msg.reply("\n".join(lines), components=mk)
        return

    if data == "admin:adm:add":
        if not is_super_admin(uid):
            await msg.reply("فقط Owner می‌تواند ادمین جدید اضافه کند.")
            return
        from handlers.user import set_state
        await set_state(uid, "admin_add_admin", {})
        await msg.reply(
            "آیدی عددی کاربر یا @username او را بفرستید:\n/cancel برای لغو"
        )
        return

    if data.startswith("admin:adm:") and data not in ("admin:adm:add",):
        parts = data.split(":")
        if len(parts) == 3:
            target = int(parts[2])
            row = await db.fetchrow("SELECT * FROM bot_admins WHERE user_id = $1", target)
            uref = await resolve_user_ref(target)
            from bale import InlineKeyboardMarkup, InlineKeyboardButton
            mk = InlineKeyboardMarkup()
            if row:
                if row.get("is_banned"):
                    mk.add(InlineKeyboardButton(text="🟢 آنبن ادمین", callback_data=f"admin:adm:unban:{target}"), row=1)
                else:
                    mk.add(InlineKeyboardButton(text="🚫 بن ادمین", callback_data=f"admin:adm:ban:{target}"), row=1)
                if row.get("is_active"):
                    mk.add(InlineKeyboardButton(text="⏹ غیرفعال کردن", callback_data=f"admin:adm:off:{target}"), row=2)
                else:
                    mk.add(InlineKeyboardButton(text="✅ فعال کردن", callback_data=f"admin:adm:on:{target}"), row=2)
                if not is_super_admin(target):
                    mk.add(InlineKeyboardButton(text="🗑 حذف ادمین", callback_data=f"admin:adm:del:{target}"), row=3)
            mk.add(InlineKeyboardButton(text="🔙 لیست ادمین", callback_data="admin:admins"), row=4)
            info = f"🛡 {uref}\n"
            if row:
                info += f"نقش: {row.get('role')}\nفعال: {row.get('is_active')}\nبن: {row.get('is_banned')}"
            else:
                info += "در جدول ادمین نیست."
            await msg.reply(info, components=mk)
            return

        action, target_s = parts[2], parts[3]
        target = int(target_s)
        if is_super_admin(target) and action in ("del", "ban", "off"):
            await msg.reply("Owner اصلی قابل حذف/بن/غیرفعال نیست.")
            return
        if action == "ban":
            await db.execute(
                "UPDATE bot_admins SET is_banned = TRUE, updated_at = NOW() WHERE user_id = $1",
                target,
            )
            await msg.reply("ادمین بن شد.", components=kb.admin_panel_kb())
        elif action == "unban":
            await db.execute(
                "UPDATE bot_admins SET is_banned = FALSE, updated_at = NOW() WHERE user_id = $1",
                target,
            )
            await msg.reply("آنبن شد.", components=kb.admin_panel_kb())
        elif action == "off":
            await db.execute(
                "UPDATE bot_admins SET is_active = FALSE, updated_at = NOW() WHERE user_id = $1",
                target,
            )
            await msg.reply("ادمین غیرفعال شد.", components=kb.admin_panel_kb())
        elif action == "on":
            await db.execute(
                "UPDATE bot_admins SET is_active = TRUE, updated_at = NOW() WHERE user_id = $1",
                target,
            )
            await msg.reply("ادمین فعال شد.", components=kb.admin_panel_kb())
        elif action == "del":
            if not is_super_admin(uid):
                await msg.reply("فقط Owner می‌تواند ادمین را حذف کند.")
                return
            await db.execute("DELETE FROM bot_admins WHERE user_id = $1 AND role != 'super'", target)
            await msg.reply("ادمین حذف شد.", components=kb.admin_panel_kb())
        else:
            await msg.reply("دستور نامعتبر.")
        return

    if data == "admin:settings":
        card, holder = await pay_svc.get_card_settings()
        await msg.reply(
            "⚙️ تنظیمات\n\n"
            f"کارت: {card}\n"
            f"صاحب حساب: {holder}\n"
            f"Owner: @{config.ADMIN_USERNAME} ({config.ADMIN_ID})\n"
            f"FREE max channels: {config.FREE_MAX_CHANNELS}\n"
            f"FREE min interval: {config.FREE_MIN_NEWS_INTERVAL_MINUTES}m\n"
            f"FREE max news/day: {config.FREE_MAX_NEWS_PER_DAY}\n\n"
            "برای تغییر کارت یا قیمت پلن‌ها از دکمه‌های پنل استفاده کنید.",
            components=kb.admin_panel_kb(),
        )
        return

    await msg.reply("دستور ادمین ناشناخته.", components=kb.admin_panel_kb())
