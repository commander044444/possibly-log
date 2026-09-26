# Bale News Automation Bot

سرویس News Automation برای Bale با دو سطح:

- 🆓 **FREE** — دائمی، واقعاً قابل استفاده، با محدودیت
- 👑 **VIP** — اشتراک پولی، 24/7، interval کوتاه

**هیچ Trial / VIP Trial وجود ندارد.**

## Stack

- `python-bale-bot==2.5.0`
- PostgreSQL + `asyncpg`
- Railway worker
- aiohttp, feedparser, Pillow, Matplotlib

## Database

در `config.py`:

```python
POSTGRESQL_URL = "postgresql://USER:PASSWORD@HOST:PORT/DATABASE"
```

اولویت با `config.POSTGRESQL_URL` است (نه فقط env).

اگر placeholder باشد و `DATABASE_URL` در محیط باشد، fallback می‌شود.

## FREE limits (قابل تنظیم در config / system_settings)

```
FREE_MAX_CHANNELS = 1
FREE_MIN_NEWS_INTERVAL_MINUTES = 180   # 3 hours
FREE_MAX_NEWS_PER_DAY = 8
FREE_MAX_SOURCES = 2
FREE_INTERVALS = [180, 360, 720, 1440]
```

FREE می‌تواند:

- کانال اضافه کند (تا سقف)
- Start/Stop اخبار
- دسته پایه
- آمار
- تیکت / FAQ

Scheduler سقف روزانه و حداقل interval را اعمال می‌کند.

## VIP

پلن‌ها از جدول `plans` خوانده می‌شوند (Admin-managed).

قیمت در لحظه ایجاد Payment در `payment_requests.amount` snapshot می‌شود.

## Run

```bash
pip install -r requirements.txt
# edit config.py: BOT_TOKEN, POSTGRESQL_URL, CARD_NUMBER
python main.py
```

Railway Procfile:

```
worker: python main.py
```

## Admin

`/admin` — فقط `ADMIN_ID = 1967315238`

## Permission model

| Feature | FREE | VIP |
|---------|------|-----|
| Add channel | limit | higher limit |
| Stats | ✅ | ✅ |
| Start news | ✅ (slow + daily cap) | ✅ (fast) |
| Interval 3–60m | ❌ | ✅ |
| Interval 3h+ | ✅ | ✅ |
| Full categories | subset | all |

DARKKNIGHT STUDIO · @commander04
