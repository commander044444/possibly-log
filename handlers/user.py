"""
User handlers — FREE / VIP limit-based (no Trial).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Optional

from bale import Message, CallbackQuery, InputFile, InlineKeyboardMarkup, InlineKeyboardButton

import config
import database as db
import keyboards as kb
from services import subscription as sub_svc
from services import payments as pay_svc
from services import statistics as stats_svc
from utils.helpers import is_admin, generate_ticket_code

logger = logging.getLogger(__name__)


async def set_state(user_id: int, state: str, data: Optional[dict] = None) -> None:
    await db.execute(
        """
        INSERT INTO user_states (user_id, state, data, updated_at)
        VALUES ($1, $2, $3::jsonb, NOW())
        ON CONFLICT (user_id) DO UPDATE SET
            state = EXCLUDED.state, data = EXCLUDED.data, updated_at = NOW()
        """,
        user_id, state, json.dumps(data or {}),
    )


async def get_state(user_id: int):
    row = await db.fetchrow(
        "SELECT state, data FROM user_states WHERE user_id = $1", user_id
    )
    if not row:
        return None, {}
    data = row["data"]
    if isinstance(data, str):
        data = json.loads(data)
    return row["state"], data or {}


async def clear_state(user_id: int) -> None:
    await db.execute("DELETE FROM user_states WHERE user_id = $1", user_id)


async def handle_start(message: Message) -> None:
    user = message.from_user or message.author
    if not user:
        return
    uid = int(user.user_id)
    await sub_svc.ensure_user(
        uid,
        getattr(user, "username", None),
        getattr(user, "first_name", None),
        getattr(user, "last_name", None),
    )
    if await sub_svc.is_banned(uid):
        await message.reply("🚫 حساب شما مسدود شده است.")
        return

    name = getattr(user, "first_name", None) or "کاربر"
    tier = await sub_svc.get_access_tier(uid)
    limits = await sub_svc.get_user_limits(uid)

    if tier == "VIP":
        text = (
            f"سلام {name} 👋\n\n"
            "سطح دسترسی: 👑 VIP\n\n"
            "📰 به ربات مدیریت اخبار خوش آمدید."
        )
    else:
        text = (
            f"سلام {name} 👋\n\n"
            "سطح دسترسی: 🆓 FREE\n\n"
            "می‌توانید کانال اضافه کنید، آمار ببینید و اخبار را "
            f"با فاصله حداقل {limits['min_interval_minutes']} دقیقه منتشر کنید.\n\n"
            "برای interval کوتاه و فعالیت 24/7، VIP تهیه کنید."
        )
    await message.reply(text, components=kb.main_menu())


async def handle_callback(callback: CallbackQuery, bot) -> None:
    data = (callback.data or "").strip()
    user = callback.from_user
    if not user:
        return
    uid = int(user.user_id)
    msg = callback.message

    await sub_svc.ensure_user(
        uid,
        getattr(user, "username", None),
        getattr(user, "first_name", None),
        getattr(user, "last_name", None),
    )
    if await sub_svc.is_banned(uid) and not is_admin(uid):
        await msg.reply("🚫 حساب شما مسدود شده است.")
        return

    if data == "menu:main":
        await msg.reply("منوی اصلی:", components=kb.main_menu())
        return

    if data == "about":
        await msg.reply(config.ABOUT_TEXT, components=kb.about_kb())
        return

    if data == "sub:status":
        text = await sub_svc.get_status_text(uid)
        comps = kb.back_main() if await sub_svc.has_vip_access(uid) else kb.vip_upgrade_kb()
        await msg.reply(text, components=comps)
        return

    # ── buy VIP
    if data == "pay:menu":
        await msg.reply("👑 خرید VIP\n\nروش پرداخت را انتخاب کنید:", components=kb.pay_method_kb())
        return

    if data.startswith("pay:method:"):
        method = data.split(":")[-1]
        plans = await sub_svc.list_enabled_plans()
        if not plans:
            await msg.reply("در حال حاضر پلنی فعال نیست. با ادمین تماس بگیرید.", components=kb.back_main())
            return
        lines = ["👑 پلن‌های VIP\n"]
        for p in plans:
            lines.append(
                f"• {p['name']}\n"
                f"  ⏱ مدت: {p['duration_days']} روز\n"
                f"  💰 قیمت: {p['price']:,} تومان\n"
            )
        if method == "gift":
            lines.append(f"\nپس از انتخاب پلن، به @{config.ADMIN_USERNAME} پیام دهید.")
        await msg.reply("\n".join(lines), components=kb.plans_from_db_kb(plans, method))
        return

    if data.startswith("pay:plan:"):
        parts = data.split(":")
        if len(parts) < 4:
            return
        method, plan_id_s = parts[2], parts[3]
        try:
            plan_id = int(plan_id_s)
        except ValueError:
            await msg.reply("پلن نامعتبر.", components=kb.back_main())
            return
        plan = await sub_svc.get_plan_by_id(plan_id)
        if not plan or not plan.get("enabled"):
            await msg.reply("پلن در دسترس نیست.", components=kb.back_main())
            return
        pid = await pay_svc.create_payment_request(uid, plan_id, method)
        if not pid:
            await msg.reply("خطا در ثبت درخواست.", components=kb.back_main())
            return
        try:
            await bot.send_message(
                chat_id=config.ADMIN_ID,
                text=(
                    f"{'🎁' if method == 'gift' else '💳'} درخواست پرداخت\n\n"
                    f"کاربر: {uid}\n"
                    f"پلن: {plan['name']}\n"
                    f"مبلغ (snapshot): {plan['price']:,}\n"
                    f"Payment ID: {pid}"
                ),
                components=kb.admin_payment_kb(pid),
            )
        except Exception:
            logger.exception("notify admin payment")
        if method == "gift":
            await msg.reply(
                f"درخواست ثبت شد (#{pid}).\n"
                f"لطفاً به @{config.ADMIN_USERNAME} پیام دهید.\n"
                "فعال‌سازی فقط پس از تایید مدیریت انجام می‌شود.",
                components=kb.back_main(),
            )
        else:
            await msg.reply(
                "درخواست کارت‌به‌کارت ثبت شد.\n"
                "پس از تایید اولیه، شماره کارت برای واریز ارسال می‌شود.",
                components=kb.back_main(),
            )
        return

    if data == "lic:enter":
        await set_state(uid, "await_license")
        await msg.reply("🔑 لطفاً کد لایسنس را ارسال کنید:", components=kb.cancel_kb())
        return

    # ── channels (FREE with limit)
    if data == "ch:add":
        ok, reason = await sub_svc.can_add_channel(uid)
        if not ok:
            await msg.reply(reason, components=kb.vip_upgrade_kb())
            return
        await set_state(uid, "await_channel")
        await msg.reply(
            "➕ اضافه کردن کانال\n\n"
            "۱. ربات را به کانال اضافه و Admin کنید.\n"
            "۲. آیدی عددی یا @username کانال را بفرستید.",
            components=kb.cancel_kb(),
        )
        return

    if data == "ch:manage":
        channels = await db.fetch(
            "SELECT * FROM channels WHERE owner_user_id = $1 AND status != 'removed'",
            uid,
        )
        if not channels:
            await msg.reply("کانالی ثبت نشده است.", components=kb.back_main())
            return
        lines = []
        for c in channels:
            st = "🟢" if c["is_active"] else "⏸"
            lines.append(
                f"{st} {c['channel_title'] or c['channel_id']} "
                f"(هر {c['news_interval']} دقیقه)"
            )
        await msg.reply("⚙️ کانال‌های شما:\n\n" + "\n".join(lines), components=kb.back_main())
        return

    if data == "ch:remove":
        channels = await db.fetch(
            "SELECT * FROM channels WHERE owner_user_id = $1 AND status != 'removed'",
            uid,
        )
        if not channels:
            await msg.reply("کانالی برای حذف نیست.", components=kb.back_main())
            return
        rows = [
            [InlineKeyboardButton(
                text=f"🗑 {c['channel_title'] or c['channel_id']}",
                callback_data=f"ch:rm:{c['channel_id']}",
            )]
            for c in channels
        ]
        rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu:main")])
        await msg.reply("کانال را انتخاب کنید:", components=InlineKeyboardMarkup(inline_keyboard=rows))
        return

    if data.startswith("ch:rm:"):
        cid = int(data.split(":")[-1])
        row = await db.fetchrow(
            "SELECT * FROM channels WHERE channel_id = $1 AND owner_user_id = $2",
            cid, uid,
        )
        if not row:
            await msg.reply("دسترسی ندارید.", components=kb.back_main())
            return
        await msg.reply(
            f"آیا از حذف «{row['channel_title']}» مطمئن هستید؟",
            components=kb.confirm_kb(f"ch:rmok:{cid}"),
        )
        return

    if data.startswith("ch:rmok:"):
        cid = int(data.split(":")[-1])
        await db.execute(
            """
            UPDATE channels SET status = 'removed', is_active = FALSE
            WHERE channel_id = $1 AND owner_user_id = $2
            """,
            cid, uid,
        )
        await msg.reply("✅ کانال حذف شد.", components=kb.main_menu())
        return

    # ── start/stop — allowed for FREE and VIP (limits enforced by scheduler)
    if data in ("news:start", "news:stop"):
        if await sub_svc.get_access_tier(uid) == "BANNED":
            await msg.reply("🚫 حساب مسدود است.")
            return
        channels = await db.fetch(
            "SELECT * FROM channels WHERE owner_user_id = $1 AND status != 'removed'",
            uid,
        )
        if not channels:
            await msg.reply("ابتدا یک کانال اضافه کنید.", components=kb.back_main())
            return
        activate = data == "news:start"
        limits = await sub_svc.get_user_limits(uid)
        # ensure intervals meet min before start
        if activate:
            for c in channels:
                if int(c["news_interval"]) < limits["min_interval_minutes"]:
                    await db.execute(
                        "UPDATE channels SET news_interval = $2 WHERE channel_id = $1",
                        c["channel_id"], limits["min_interval_minutes"],
                    )
        await db.execute(
            """
            UPDATE channels SET is_active = $2, status = $3, updated_at = NOW()
            WHERE owner_user_id = $1 AND status != 'removed'
            """,
            uid, activate, "active" if activate else "stopped",
        )
        if activate:
            extra = ""
            if limits["tier"] == "FREE":
                extra = (
                    f"\n\nپلن FREE:\n"
                    f"• حداقل فاصله: {limits['min_interval_minutes']} دقیقه\n"
                    f"• حداکثر خبر روزانه: {limits['max_news_per_day']}"
                )
            await msg.reply(
                f"▶️ فعالیت خبری شروع شد.{extra}",
                components=kb.main_menu(),
            )
        else:
            await msg.reply("⏸ فعالیت خبری متوقف شد.", components=kb.main_menu())
        return

    # ── interval
    if data == "ch:interval_menu":
        limits = await sub_svc.get_user_limits(uid)
        await msg.reply(
            f"⏱ فاصله ارسال را انتخاب کنید "
            f"(حداقل مجاز پلن شما: {limits['min_interval_minutes']} دقیقه):",
            components=kb.intervals_kb(limits["intervals"]),
        )
        return

    if data.startswith("ch:interval:"):
        mins = int(data.split(":")[-1])
        ok, reason = await sub_svc.validate_interval(uid, mins)
        if not ok:
            await msg.reply(reason, components=kb.vip_upgrade_kb())
            return
        await db.execute(
            """
            UPDATE channels SET news_interval = $2, updated_at = NOW()
            WHERE owner_user_id = $1 AND status != 'removed'
            """,
            uid, mins,
        )
        label = f"{mins // 60} ساعت" if mins >= 60 else f"{mins} دقیقه"
        await msg.reply(f"✅ فاصله ارسال: {label}", components=kb.main_menu())
        return

    # ── categories
    if data == "cat:menu":
        limits = await sub_svc.get_user_limits(uid)
        allowed = (
            list(config.CATEGORIES.keys())
            if limits["tier"] == "VIP"
            else list(config.FREE_CATEGORIES)
        )
        ch = await db.fetchrow(
            "SELECT channel_id FROM channels WHERE owner_user_id = $1 AND status != 'removed' LIMIT 1",
            uid,
        )
        selected = []
        if ch:
            rows = await db.fetch(
                "SELECT category_key FROM channel_categories WHERE channel_id = $1",
                ch["channel_id"],
            )
            selected = [r["category_key"] for r in rows]
        await msg.reply(
            "دسته‌بندی‌ها را انتخاب کنید:",
            components=kb.categories_kb(selected, allowed),
        )
        return

    if data.startswith("cat:toggle:") or data in ("cat:all", "cat:clear"):
        limits = await sub_svc.get_user_limits(uid)
        allowed = (
            set(config.CATEGORIES.keys())
            if limits["tier"] == "VIP"
            else set(config.FREE_CATEGORIES)
        )
        ch = await db.fetchrow(
            "SELECT channel_id FROM channels WHERE owner_user_id = $1 AND status != 'removed' LIMIT 1",
            uid,
        )
        if not ch:
            await msg.reply("ابتدا کانال اضافه کنید.", components=kb.back_main())
            return
        cid = ch["channel_id"]
        if data == "cat:clear":
            await db.execute("DELETE FROM channel_categories WHERE channel_id = $1", cid)
        elif data == "cat:all":
            for key in allowed:
                await db.execute(
                    "INSERT INTO channel_categories (channel_id, category_key) VALUES ($1,$2) ON CONFLICT DO NOTHING",
                    cid, key,
                )
        else:
            key = data.split(":")[-1]
            if key not in allowed:
                await msg.reply(
                    "این دسته در پلن FREE در دسترس نیست. VIP تهیه کنید.",
                    components=kb.vip_upgrade_kb(),
                )
                return
            exists = await db.fetchval(
                "SELECT 1 FROM channel_categories WHERE channel_id = $1 AND category_key = $2",
                cid, key,
            )
            if exists:
                await db.execute(
                    "DELETE FROM channel_categories WHERE channel_id = $1 AND category_key = $2",
                    cid, key,
                )
            else:
                await db.execute(
                    "INSERT INTO channel_categories (channel_id, category_key) VALUES ($1,$2) ON CONFLICT DO NOTHING",
                    cid, key,
                )
        rows = await db.fetch(
            "SELECT category_key FROM channel_categories WHERE channel_id = $1", cid
        )
        selected = [r["category_key"] for r in rows]
        await msg.reply("به‌روز شد:", components=kb.categories_kb(selected, list(allowed)))
        return

    # ── stats FREE
    if data == "stats:menu":
        channels = await db.fetch(
            "SELECT * FROM channels WHERE owner_user_id = $1 AND status != 'removed'",
            uid,
        )
        if not channels:
            await msg.reply("کانالی ثبت نشده است.", components=kb.back_main())
            return
        rows = [
            [InlineKeyboardButton(
                text=f"📊 {c['channel_title'] or c['channel_id']}",
                callback_data=f"stats:show:{c['channel_id']}",
            )]
            for c in channels
        ]
        rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu:main")])
        await msg.reply("کانال را انتخاب کنید:", components=InlineKeyboardMarkup(inline_keyboard=rows))
        return

    if data.startswith("stats:show:"):
        cid = int(data.split(":")[-1])
        row = await db.fetchrow(
            "SELECT * FROM channels WHERE channel_id = $1 AND owner_user_id = $2",
            cid, uid,
        )
        if not row:
            await msg.reply("دسترسی ندارید.", components=kb.back_main())
            return
        summary = await stats_svc.get_channel_stats_summary(cid)
        png = stats_svc.render_stats_image(
            row["channel_title"] or str(cid),
            row.get("channel_username"),
            summary,
        )
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(png)
                path = f.name
            await bot.send_photo(
                chat_id=uid,
                photo=InputFile(path),
                caption=f"📊 آمار «{row['channel_title']}»",
            )
            os.unlink(path)
        except Exception:
            logger.exception("send stats")
            await msg.reply(
                f"امروز: {summary['today_messages']} | هفته: {summary['week_messages']} | ماه: {summary['month_messages']}",
                components=kb.back_main(),
            )
        return

    if data == "support:menu":
        await msg.reply("🛠 پیگیری مشکلات\n\nدسته را انتخاب کنید:", components=kb.support_menu_kb())
        return

    if data.startswith("support:cat:"):
        cat = data.split(":")[-1]
        await set_state(uid, "await_ticket", {"category": cat})
        await msg.reply(
            "لطفاً مشکل را کامل بنویسید. پس از ارسال، تیکت ثبت می‌شود.",
            components=kb.cancel_kb(),
        )
        return

    if data == "faq:menu":
        await msg.reply("❓ سوالات متداول:", components=kb.faq_menu_kb())
        return

    if data.startswith("faq:"):
        section = data.split(":")[-1]
        texts = {
            "free": (
                "🆓 FREE\n\n"
                "پلن رایگان دائمی است و News Automation دارد، "
                "اما با محدودیت فاصله انتشار و تعداد خبر روزانه.\n"
                "کانال و آمار همیشه رایگان‌اند."
            ),
            "vip": (
                "👑 VIP\n\n"
                "interval کوتاه، کانال بیشتر، بدون سقف روزانه "
                "(طبق پلن)، دسته‌بندی کامل و فعالیت 24/7."
            ),
            "channel": (
                "📺 کانال\n\n"
                "اضافه کردن کانال در FREE تا سقف مشخص مجاز است. "
                "برای کانال بیشتر VIP بخرید. کانال‌های قبلی حذف نمی‌شوند."
            ),
            "stats": "📊 آمار کانال برای همه رایگان است.",
            "license": "🔑 لایسنس پس از تایید پرداخت صادر می‌شود و یک‌بارمصرف است.",
            "news": "📰 Start فعالیت اخبار را طبق interval و سقف روزانه پلن شما منتشر می‌کند.",
            "support": "🛠 از بخش پیگیری مشکلات تیکت باز کنید.",
            "pay": "💰 پاکت هدیه یا کارت‌به‌کارت؛ قیمت از پلن‌های فعال Database خوانده می‌شود.",
        }
        await msg.reply(texts.get(section, "بخش یافت نشد."), components=kb.faq_menu_kb())
        return

    if data.startswith("admin:") and is_admin(uid):
        from handlers.admin import handle_admin_callback
        await handle_admin_callback(callback, bot)
        return


async def handle_text_message(message: Message, bot) -> None:
    user = message.from_user or message.author
    if not user:
        return
    uid = int(user.user_id)
    text = (message.content or message.text or "").strip()

    if text.startswith("/start"):
        await handle_start(message)
        return
    if text == "/admin" and is_admin(uid):
        await message.reply("پنل مدیریت:", components=kb.admin_panel_kb())
        return

    if not text:
        await _maybe_receipt_photo(message, bot)
        return

    state, data = await get_state(uid)

    if state == "await_license":
        ok, resp = await pay_svc.redeem_license(uid, text)
        await clear_state(uid)
        await message.reply(resp, components=kb.main_menu())
        return

    if state == "await_ticket":
        cat = (data or {}).get("category", "other")
        code = generate_ticket_code()
        await db.execute(
            """
            INSERT INTO tickets (ticket_code, user_id, category, message, status)
            VALUES ($1, $2, $3, $4, 'open')
            """,
            code, uid, cat, text[:4000],
        )
        await clear_state(uid)
        await message.reply(f"✅ تیکت ثبت شد.\nکد: {code}", components=kb.main_menu())
        try:
            await bot.send_message(
                chat_id=config.ADMIN_ID,
                text=f"🎫 {code}\nuser={uid}\n{cat}\n\n{text[:1500]}",
            )
        except Exception:
            pass
        return

    if state == "await_channel":
        await clear_state(uid)
        ok, reason = await sub_svc.can_add_channel(uid)
        if not ok:
            await message.reply(reason, components=kb.vip_upgrade_kb())
            return
        channel_id = None
        username = None
        title = text
        if text.startswith("@"):
            username = text[1:]
        elif text.lstrip("-").isdigit():
            channel_id = int(text)
        else:
            await message.reply(
                "آیدی عددی یا @username بفرستید.",
                components=kb.back_main(),
            )
            return
        try:
            chat = await bot.get_chat(channel_id if channel_id else username)
            channel_id = int(chat.id)
            title = getattr(chat, "title", None) or title
            username = getattr(chat, "username", None) or username
        except Exception as e:
            logger.warning("get_chat failed: %s", e)
            await message.reply(
                "کانال پیدا نشد یا ربات Admin نیست.",
                components=kb.back_main(),
            )
            return

        limits = await sub_svc.get_user_limits(uid)
        default_iv = limits["min_interval_minutes"]
        await db.execute(
            """
            INSERT INTO channels
                (channel_id, channel_username, channel_title, owner_user_id, status, is_active, news_interval)
            VALUES ($1, $2, $3, $4, 'registered', FALSE, $5)
            ON CONFLICT (channel_id) DO UPDATE SET
                channel_username = EXCLUDED.channel_username,
                channel_title = EXCLUDED.channel_title,
                owner_user_id = EXCLUDED.owner_user_id,
                status = 'registered',
                updated_at = NOW()
            """,
            channel_id, username, title, uid, default_iv,
        )
        await db.execute(
            "INSERT INTO channel_settings (channel_id) VALUES ($1) ON CONFLICT DO NOTHING",
            channel_id,
        )
        await message.reply(
            f"✅ کانال «{title}» ثبت شد.\n"
            f"فاصله پیش‌فرض: {default_iv} دقیقه (پلن {limits['tier']}).\n"
            "می‌توانید دسته را انتخاب و Start کنید.",
            components=kb.main_menu(),
        )
        return

    if state == "await_receipt":
        await message.reply(
            "لطفاً اسکرین‌شات واریزی را به‌صورت عکس بفرستید.",
            components=kb.cancel_kb(),
        )
        return


async def _maybe_receipt_photo(message: Message, bot) -> None:
    user = message.from_user or message.author
    if not user:
        return
    uid = int(user.user_id)
    state, data = await get_state(uid)
    if state != "await_receipt":
        return
    payment_id = (data or {}).get("payment_id")
    if not payment_id:
        await clear_state(uid)
        return
    photos = getattr(message, "photos", None) or []
    file_id = None
    if photos:
        file_id = getattr(photos[-1], "file_id", None) or str(photos[-1])
    if not file_id:
        await message.reply("عکس معتبر دریافت نشد.")
        return
    ok, _ = await pay_svc.transition_payment(
        payment_id, "under_review", receipt_file_id=str(file_id)
    )
    await clear_state(uid)
    if not ok:
        await message.reply("وضعیت درخواست قابل به‌روزرسانی نیست.", components=kb.back_main())
        return
    await message.reply("📸 رسید برای بررسی ارسال شد.", components=kb.back_main())
    try:
        await bot.send_message(
            chat_id=config.ADMIN_ID,
            text=f"📸 رسید پرداخت #{payment_id} از کاربر {uid}",
            components=kb.admin_receipt_kb(payment_id),
        )
    except Exception:
        logger.exception("notify receipt")
