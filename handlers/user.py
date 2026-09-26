"""
User handlers — FREE / VIP limit-based (no Trial).
"""
from __future__ import annotations

import json
import re
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
from utils.helpers import is_admin, generate_ticket_code, resolve_user_ref, format_user_ref

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
            uref = await resolve_user_ref(uid)
            emoji = "🎁" if method == "gift" else "💳"
            await bot.send_message(
                chat_id=config.ADMIN_ID,
                text=(
                    emoji + " درخواست پرداخت\n\n"
                    + f"کاربر: {uref}\n"
                    + f"پلن: {plan['name']}\n"
                    + f"مبلغ (snapshot): {plan['price']:,}\n"
                    + f"Payment ID: {pid}"
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
            "۱. ربات را به کانال اضافه کنید و Admin بگذارید\n"
            "(اجازه ارسال پیام / Post).\n\n"
            "۲. یکی از این‌ها را بفرستید:\n"
            "• آیدی عددی کانال\n"
            "• @username\n"
            "• یک پیام فورواردشده از همان کانال",
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
        mk = InlineKeyboardMarkup()
        for i, c in enumerate(channels, start=1):
            mk.add(
                InlineKeyboardButton(
                    text=f"🗑 {c['channel_title'] or c['channel_id']}",
                    callback_data=f"ch:rm:{c['channel_id']}",
                ),
                row=i,
            )
        mk.add(InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu:main"), row=len(channels) + 1)
        await msg.reply("کانال را انتخاب کنید:", components=mk)
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
        mk = InlineKeyboardMarkup()
        for i, c in enumerate(channels, start=1):
            mk.add(
                InlineKeyboardButton(
                    text=f"📊 {c['channel_title'] or c['channel_id']}",
                    callback_data=f"stats:show:{c['channel_id']}",
                ),
                row=i,
            )
        mk.add(InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu:main"), row=len(channels) + 1)
        await msg.reply("کانال را انتخاب کنید:", components=mk)
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

        await msg.reply("⏳ در حال ساخت گزارش تصویری…")

        members = None
        bio = row.get("channel_bio")
        avatar_bytes = None
        title = row["channel_title"] or str(cid)
        uname = row.get("channel_username")
        try:
            chat = await _get_chat_flexible(bot, cid)
            if chat is not None:
                title = getattr(chat, "title", None) or title
                uname = getattr(chat, "username", None) or uname
                bio = getattr(chat, "description", None) or getattr(chat, "bio", None) or bio
                try:
                    members = await bot.get_chat_members_count(cid)
                except Exception:
                    try:
                        members = await bot.get_chat_members_count(str(cid))
                    except Exception as e:
                        logger.warning("members_count failed: %s", e)
                photo = getattr(chat, "photo", None)
                if photo is not None:
                    # python-bale-bot ChatPhoto: get_big_file() / get_small_file() -> bytes
                    for method_name in ("get_big_file", "get_small_file"):
                        meth = getattr(photo, method_name, None)
                        if meth is None:
                            continue
                        try:
                            data = await meth()
                            if isinstance(data, (bytes, bytearray)) and len(data) > 100:
                                avatar_bytes = bytes(data)
                                logger.info("avatar via %s (%s bytes)", method_name, len(avatar_bytes))
                                break
                        except Exception as e:
                            logger.warning("avatar %s failed: %s", method_name, e)
                    if avatar_bytes is None:
                        for attr in ("big_file_id", "small_file_id"):
                            fid = getattr(photo, attr, None)
                            if not fid:
                                continue
                            try:
                                data = await bot.get_file(fid)
                                if isinstance(data, (bytes, bytearray)) and len(data) > 100:
                                    avatar_bytes = bytes(data)
                                    logger.info("avatar via get_file(%s) %s bytes", attr, len(avatar_bytes))
                                    break
                            except Exception as e:
                                logger.warning("get_file %s failed: %s", attr, e)
        except Exception:
            logger.exception("live channel meta")

        if members is not None:
            await stats_svc.snapshot_members(cid, members)

        summary = await stats_svc.get_channel_stats_summary(cid)
        try:
            png = stats_svc.render_stats_image(
                title, uname, summary,
                bio=bio, members=members, avatar_bytes=avatar_bytes,
                channel_id=cid,
            )
        except Exception:
            logger.exception("render stats image")
            png = None

        sent = False
        if png:
            # official API: InputFile(bytes) or path string for reply_photo
            try:
                photo_obj = InputFile(png, file_name="stats.png")
            except TypeError:
                try:
                    photo_obj = InputFile(png)
                except Exception:
                    photo_obj = None
            if photo_obj is not None:
                try:
                    await bot.send_photo(
                        chat_id=uid,
                        photo=photo_obj,
                        caption=f"📊 آمار «{title}»",
                    )
                    sent = True
                except Exception:
                    logger.exception("send_photo InputFile bytes")
                if not sent:
                    try:
                        await msg.reply_photo(
                            photo=photo_obj,
                            caption=f"📊 آمار «{title}»",
                        )
                        sent = True
                    except Exception:
                        logger.exception("reply_photo InputFile")
            if not sent:
                path = None
                try:
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                        f.write(png)
                        path = f.name
                    try:
                        await bot.send_photo(
                            chat_id=uid,
                            photo=InputFile(path),
                            caption=f"📊 آمار «{title}»",
                        )
                        sent = True
                    except Exception:
                        logger.exception("send_photo path")
                    if not sent:
                        try:
                            await msg.reply_photo(
                                photo=path,
                                caption=f"📊 آمار «{title}»",
                            )
                            sent = True
                        except Exception:
                            logger.exception("reply_photo path")
                finally:
                    if path:
                        try:
                            os.unlink(path)
                        except Exception:
                            pass

        if not sent:
            # full text report (not a stub)
            s = summary
            text = (
                f"📊 آمار «{title}»\n"
                + (f"@{uname}\n" if uname else "")
                + f"\n📅 گزارش: {s.get('report_date', '—')}\n"
                f"👥 اعضا: {s.get('members_now') if s.get('members_now') is not None else (members if members is not None else 'N/A')}\n"
                f"+7d: {s.get('joined_7d') if s.get('joined_7d') is not None else 'N/A'} | "
                f"-7d: {s.get('left_7d') if s.get('left_7d') is not None else 'N/A'}\n"
                f"+30d: {s.get('joined_30d') if s.get('joined_30d') is not None else 'N/A'} | "
                f"-30d: {s.get('left_30d') if s.get('left_30d') is not None else 'N/A'}\n\n"
                f"📨 امروز: {s.get('today_messages', 0)}\n"
                f"📨 ۷ روز: {s.get('week_messages', 0)}\n"
                f"📨 ۳۰ روز: {s.get('month_messages', 0)}\n"
                f"📨 کل ثبت‌شده: {s.get('total_messages', 0)}\n\n"
                f"متن: {s.get('text', 0)} | عکس: {s.get('photo', 0)} | ویدیو: {s.get('video', 0)}\n"
                f"GIF: {s.get('gif', 0)} | ویس: {s.get('voice', 0)} | صوت: {s.get('audio', 0)}\n"
                f"فایل: {s.get('file', 0)} | استیکر: {s.get('sticker', 0)}\n\n"
                "⚠️ ارسال تصویر در این محیط ناموفق بود؛ گزارش متنی کامل بالا است."
            )
            await msg.reply(text, components=kb.back_main())
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

    # admin compose message / broadcast
    state, data = await get_state(uid)
    if state == "admin_msg_user" and is_admin(uid):
        target = (data or {}).get("target_id")
        if text in ("/cancel", "لغو"):
            await clear_state(uid)
            await message.reply("لغو شد.", components=kb.admin_panel_kb() if hasattr(kb, "admin_panel_kb") else kb.back_main())
            return
        if target:
            try:
                await bot.send_message(chat_id=int(target), text=f"📨 پیام مدیریت:\n\n{text}")
                await message.reply("✅ ارسال شد.", components=kb.admin_panel_kb())
            except Exception as e:
                await message.reply(f"ارسال ناموفق: {e}")
            await clear_state(uid)
            return
    if state == "admin_broadcast" and is_admin(uid):
        if text in ("/cancel", "لغو"):
            await clear_state(uid)
            await message.reply("لغو شد.", components=kb.admin_panel_kb())
            return
        users = await db.fetch("SELECT user_id FROM users WHERE COALESCE(is_banned, FALSE) = FALSE")
        ok = fail = 0
        for u in users:
            try:
                await bot.send_message(chat_id=int(u["user_id"]), text=f"📢 پیام مدیریت:\n\n{text}")
                ok += 1
            except Exception:
                fail += 1
        await clear_state(uid)
        await message.reply(f"Broadcast تمام شد. موفق: {ok} | ناموفق: {fail}", components=kb.admin_panel_kb())
        return


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
            uref = await resolve_user_ref(uid)
            _u = message.from_user or message.author
            if _u and getattr(_u, "username", None):
                uref = format_user_ref(_u.username, uid)
            await bot.send_message(
                chat_id=config.ADMIN_ID,
                text=f"🎫 {code}\nکاربر: {uref}\n{cat}\n\n{text[:1500]}",
            )
        except Exception:
            pass
        return

    if state == "await_channel":
        ok, reason = await sub_svc.can_add_channel(uid)
        if not ok:
            await clear_state(uid)
            await message.reply(reason, components=kb.vip_upgrade_kb())
            return

        # 1) اگر پیام فوروارد از کانال باشد
        fwd_chat = getattr(message, "forward_from_chat", None)
        if fwd_chat is not None:
            resolved = await _resolve_channel_from_chat_obj(bot, fwd_chat)
        else:
            resolved = await _resolve_channel_from_text(bot, text)

        if not resolved.get("ok"):
            # state را نگه می‌داریم تا کاربر دوباره تلاش کند
            await message.reply(
                resolved.get("error")
                or (
                    "❌ کانال پیدا نشد.\n\n"
                    "لطفاً یکی از موارد زیر را بفرستید:\n"
                    "• آیدی عددی کانال (مثلاً 1234567890)\n"
                    "• @username کانال\n"
                    "• یک پیام فوروارد شده از همان کانال\n\n"
                    "و مطمئن شوید ربات را Admin کرده‌اید و اجازه Post دارد."
                ),
                components=kb.cancel_kb(),
            )
            return

        await clear_state(uid)
        channel_id = resolved["channel_id"]
        title = resolved.get("title") or str(channel_id)
        username = resolved.get("username")

        limits = await sub_svc.get_user_limits(uid)
        default_iv = limits["min_interval_minutes"]
        await db.execute(
            """
            INSERT INTO channels
                (channel_id, channel_username, channel_title, owner_user_id, status, is_active, news_interval)
            VALUES ($1, $2, $3, $4, 'registered', FALSE, $5)
            ON CONFLICT (channel_id) DO UPDATE SET
                channel_username = COALESCE(EXCLUDED.channel_username, channels.channel_username),
                channel_title = COALESCE(EXCLUDED.channel_title, channels.channel_title),
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
        admin_note = ""
        if resolved.get("bot_is_admin") is False:
            admin_note = (
                "\n\n⚠️ ربات به‌عنوان Admin تشخیص داده نشد.\n"
                "برای انتشار اخبار، ربات را Admin کنید و اجازه ارسال پیام بدهید."
            )
        elif resolved.get("bot_is_admin") is True:
            admin_note = "\n\n✅ دسترسی Admin ربات تایید شد."

        await message.reply(
            f"✅ کانال «{title}» ثبت شد.\n"
            f"آیدی: `{channel_id}`\n"
            f"فاصله پیش‌فرض: {default_iv} دقیقه (پلن {limits['tier']})."
            f"{admin_note}\n\n"
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
        uref = await resolve_user_ref(uid)
        uname = getattr(user, "username", None)
        if uname:
            uref = format_user_ref(uname, uid)
        await bot.send_message(
            chat_id=config.ADMIN_ID,
            text=f"📸 رسید پرداخت #{payment_id} از {uref}",
            components=kb.admin_receipt_kb(payment_id),
        )
    except Exception:
        logger.exception("notify receipt")


# ─── Channel resolution helpers (python-bale-bot 2.5.0) ─

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _normalize_digits(s: str) -> str:
    return (s or "").translate(_PERSIAN_DIGITS).strip()


def _parse_channel_ref(raw: str):
    """
    Parse user input into either numeric channel_id or username.
    Accepts: @name, name, numeric id, ble.ir/name links.
    """
    s = _normalize_digits(raw)
    if not s:
        return None, None

    # strip common prefixes / urls
    s = s.replace("https://", "").replace("http://", "")
    for prefix in ("ble.ir/", "bale.ai/", "t.me/", "telegram.me/"):
        if prefix in s.lower():
            s = s.split(prefix, 1)[-1]
            break
    s = s.strip().strip("/")

    if s.startswith("@"):
        s = s[1:]

    # pure numeric (optional leading -)
    if s.lstrip("-").isdigit():
        try:
            return int(s), None
        except ValueError:
            return None, None

    # username: letters, digits, underscore
    if re.fullmatch(r"[A-Za-z0-9_]{3,64}", s):
        return None, s

    return None, None


async def _get_chat_flexible(bot, chat_ref) -> Optional[object]:
    """Try get_chat with int/str and use_cache=False."""
    candidates = []
    if isinstance(chat_ref, int):
        candidates = [chat_ref, str(chat_ref)]
    else:
        candidates = [chat_ref, f"@{chat_ref}" if not str(chat_ref).startswith("@") else chat_ref]

    last_err = None
    for ref in candidates:
        try:
            chat = await bot.get_chat(ref, use_cache=False)
            if chat is not None:
                return chat
        except TypeError:
            # older signature without use_cache
            try:
                chat = await bot.get_chat(ref)
                if chat is not None:
                    return chat
            except Exception as e:
                last_err = e
                logger.warning("get_chat(%r) failed: %s", ref, e)
        except Exception as e:
            last_err = e
            logger.warning("get_chat(%r) failed: %s", ref, e)
    if last_err:
        logger.warning("get_chat all candidates failed last=%s", last_err)
    return None


async def _check_bot_admin(bot, channel_id) -> Optional[bool]:
    """Return True/False if checkable, None if unknown."""
    try:
        me = bot.user
        bot_id = getattr(me, "user_id", None) or getattr(me, "id", None)
        if bot_id is None:
            return None
        member = await bot.get_chat_member(channel_id, bot_id)
        if member is None:
            return False
        status = (getattr(member, "status", None) or "").lower()
        if status in ("administrator", "creator", "admin", "owner"):
            return True
        # some Bale builds use can_post_messages
        if getattr(member, "can_post_messages", None) is True:
            return True
        return False
    except Exception as e:
        logger.warning("get_chat_member failed for %s: %s", channel_id, e)
        return None


async def _resolve_channel_from_chat_obj(bot, chat_obj) -> dict:
    try:
        cid = getattr(chat_obj, "id", None)
        if cid is None:
            return {"ok": False, "error": "آیدی کانال از فوروارد خوانده نشد."}
        channel_id = int(cid)
        title = getattr(chat_obj, "title", None) or str(channel_id)
        username = getattr(chat_obj, "username", None)
        # refresh via API when possible
        refreshed = await _get_chat_flexible(bot, channel_id)
        if refreshed is not None:
            title = getattr(refreshed, "title", None) or title
            username = getattr(refreshed, "username", None) or username
            channel_id = int(getattr(refreshed, "id", channel_id))
        admin = await _check_bot_admin(bot, channel_id)
        return {
            "ok": True,
            "channel_id": channel_id,
            "title": title,
            "username": username,
            "bot_is_admin": admin,
        }
    except Exception as e:
        logger.exception("resolve from forward failed")
        return {"ok": False, "error": f"خطا در خواندن کانال فوروارد شده: {e}"}


async def _resolve_channel_from_text(bot, raw: str) -> dict:
    channel_id, username = _parse_channel_ref(raw)
    if channel_id is None and not username:
        return {
            "ok": False,
            "error": (
                "فرمت نامعتبر است.\n\n"
                "بفرستید:\n"
                "• آیدی عددی\n"
                "• @username\n"
                "• یا یک پیام فوروارد از کانال"
            ),
        }

    ref = channel_id if channel_id is not None else username
    chat = await _get_chat_flexible(bot, ref)

    if chat is None:
        # اگر فقط آیدی عددی داده شده، ثبت با همان آیدی (fallback)
        # چون بعضی کانال‌های Bale با get_chat مشکل دارند ولی send کار می‌کند
        if channel_id is not None:
            admin = await _check_bot_admin(bot, channel_id)
            return {
                "ok": True,
                "channel_id": int(channel_id),
                "title": str(channel_id),
                "username": None,
                "bot_is_admin": admin,
            }
        return {
            "ok": False,
            "error": (
                "❌ کانال با این @username پیدا نشد.\n\n"
                "• نام کاربری را دقیق بفرستید\n"
                "• یا آیدی عددی را بفرستید\n"
                "• یا یک پست از کانال را برای ربات Forward کنید\n"
                "• ربات باید عضو/ادمین کانال باشد"
            ),
        }

    try:
        cid = int(getattr(chat, "id"))
    except Exception:
        return {"ok": False, "error": "آیدی کانال از پاسخ API قابل خواندن نبود."}

    title = getattr(chat, "title", None) or str(cid)
    uname = getattr(chat, "username", None) or username
    admin = await _check_bot_admin(bot, cid)
    return {
        "ok": True,
        "channel_id": cid,
        "title": title,
        "username": uname,
        "bot_is_admin": admin,
    }
