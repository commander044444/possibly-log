"""Admin panel — plans, payments, licenses. Only ADMIN_ID."""
from __future__ import annotations

import logging

from bale import CallbackQuery

import config
import database as db
import keyboards as kb
from services import payments as pay_svc
from services import subscription as sub_svc
from utils.helpers import is_admin

logger = logging.getLogger(__name__)


async def handle_admin_callback(callback: CallbackQuery, bot) -> None:
    data = (callback.data or "").strip()
    user = callback.from_user
    if not user or not is_admin(int(user.user_id)):
        return
    msg = callback.message
    uid = int(user.user_id)

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
            await msg.reply("پلنی نیست. از seed migration یا SQL اضافه کنید.", components=kb.admin_panel_kb())
            return
        lines = ["💳 پلن‌ها\n"]
        for p in plans:
            st = "🟢" if p["enabled"] else "🔴"
            lines.append(
                f"{st} #{p['id']} {p['name']} | {p['price']:,}ت | {p['duration_days']}روز | "
                f"ch={p['max_channels']} iv={p['min_interval_minutes']}m"
            )
        lines.append(
            "\nبرای ایجاد/ویرایش از SQL یا توسعه state-based استفاده کنید:\n"
            "INSERT INTO plans (name, slug, description, price, duration_days, "
            "max_channels, min_interval_minutes, max_news_per_day, max_sources, enabled) VALUES (...)"
        )
        await msg.reply("\n".join(lines), components=kb.admin_panel_kb())
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
            await bot.send_message(
                chat_id=uid,
                text=(
                    f"#{r['id']} | {r['method']} | {r['status']}\n"
                    f"user={r['user_id']} plan={r['plan_name'] or r['plan_key']} "
                    f"amount={r['amount']:,}"
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
                # try from pending
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

    if data == "admin:users":
        total = await db.fetchval("SELECT COUNT(*) FROM users")
        await msg.reply(f"تعداد کاربران: {total}", components=kb.admin_panel_kb())
        return

    if data == "admin:channels":
        total = await db.fetchval("SELECT COUNT(*) FROM channels WHERE status != 'removed'")
        active = await db.fetchval("SELECT COUNT(*) FROM channels WHERE is_active")
        await msg.reply(f"کانال‌ها: {total} | فعال: {active}", components=kb.admin_panel_kb())
        return

    if data == "admin:tickets":
        rows = await db.fetch(
            "SELECT * FROM tickets WHERE status = 'open' ORDER BY id DESC LIMIT 15"
        )
        if not rows:
            await msg.reply("تیکت بازی نیست.", components=kb.admin_panel_kb())
            return
        for t in rows:
            await bot.send_message(
                chat_id=uid,
                text=f"{t['ticket_code']} | {t['category']}\nuser={t['user_id']}\n{t['message'][:500]}",
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

    if data in (
        "admin:ban", "admin:unban", "admin:broadcast",
        "admin:licenses", "admin:settings",
    ):
        await msg.reply(
            "این بخش از طریق دیتابیس/توسعه بعدی قابل گسترش است.\n"
            "Ban: UPDATE users SET is_banned=TRUE WHERE user_id=...\n"
            "تنظیم FREE limits: system_settings keys free_max_channels, free_min_interval, ...",
            components=kb.admin_panel_kb(),
        )
        return

    await msg.reply("دستور ادمین ناشناخته.", components=kb.admin_panel_kb())
