from bale import Bot, Message, InputFile


# ==========================
# تنظیمات
# ==========================

TOKEN = "1136047890:50pbkHl72PKOZ-TOgO0k27_mjea_GNEgDms"

SOURCE_CHAT = 5034881088
DEST_CHAT = 4393169931

bot = Bot(TOKEN)


# ==========================
# اطلاعات فرستنده
# ==========================

def get_sender_info(message):

    sender_name = "ناشناس"
    sender_id = "نامشخص"

    if message.from_user:

        sender_id = message.from_user.id

        sender_name = message.from_user.first_name or ""

        if message.from_user.last_name:
            sender_name += f" {message.from_user.last_name}"

        if message.from_user.username:
            sender_name += f" (@{message.from_user.username})"

    return sender_name, sender_id


# ==========================
# آماده
# ==========================

@bot.event
async def on_ready():

    print("================================")
    print("✅ ربات روشن شد")
    print("📡 لاگ‌گیری فعال است")
    print("================================")


# ==========================
# دریافت پیام
# ==========================

@bot.event
async def on_message(message: Message):

    # فقط چت مبدأ
    if not message.chat:
        return

    if str(message.chat.id) != str(SOURCE_CHAT):
        return


    # ==========================
    # اطلاعات فرستنده
    # ==========================

    sender_name, sender_id = get_sender_info(message)

    header = (
        f"👤 فرستنده: {sender_name}\n"
        f"🆔 آیدی: {sender_id}\n\n"
    )


    try:

        # ==========================
        # متن
        # ==========================

        if message.text:

            await bot.send_message(
                DEST_CHAT,
                header + message.text
            )

            print("✅ متن")


        # ==========================
        # عکس
        # ==========================

        elif message.photos:

            photo = message.photos[-1]

            await bot.send_photo(
                DEST_CHAT,
                photo=InputFile(photo.file_id),
                caption=header + (message.caption or "")
            )

            print("✅ عکس")


        # ==========================
        # ویدیو
        # ==========================

        elif message.video:

            await bot.send_video(
                DEST_CHAT,
                video=InputFile(message.video.file_id),
                caption=header + (message.caption or "")
            )

            print("✅ ویدیو")


        # ==========================
        # GIF / Animation
        # ==========================

        elif getattr(message, "animation", None):

            animation = message.animation

            await bot.send_animation(
                DEST_CHAT,
                animation=InputFile(animation.file_id),
                caption=header + (message.caption or "")
            )

            print("✅ GIF")


        # ==========================
        # فایل / Document
        # ==========================

        elif message.document:

            document = message.document

            await bot.send_document(
                DEST_CHAT,
                document=InputFile(document.file_id),
                caption=header + (message.caption or "")
            )

            print("✅ فایل")


        # ==========================
        # Voice
        # ==========================

        elif getattr(message, "voice", None):

            voice = message.voice

            await bot.send_voice(
                DEST_CHAT,
                voice=InputFile(voice.file_id)
            )

            await bot.send_message(
                DEST_CHAT,
                header + "🎤 ویس بالا"
            )

            print("✅ ویس")


        # ==========================
        # Audio / Music
        # ==========================

        elif message.audio:

            audio = message.audio

            await bot.send_audio(
                DEST_CHAT,
                audio=InputFile(audio.file_id),
                caption=header + (message.caption or "")
            )

            print("✅ صدا")


        # ==========================
        # پیام ناشناخته
        # ==========================

        else:

            await bot.send_message(
                DEST_CHAT,
                header + "📩 پیام ناشناخته دریافت شد"
            )

            print("⚠️ ناشناخته")


    # ==========================
    # خطا
    # ==========================

    except Exception as e:

        print(f"❌ خطا: {e}")

        try:

            await bot.send_message(
                DEST_CHAT,
                header +
                f"⚠️ خطا در ارسال مدیا:\n{e}"
            )

        except Exception as send_error:

            print(
                f"❌ خطا در ارسال پیام خطا: {send_error}"
            )


# ==========================
# اجرا
# ==========================

bot.run()
