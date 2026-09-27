"""
Payment request flow + license generation & redemption.
Price is snapshotted on payment creation from plans table.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional, Tuple

import database as db
from utils.helpers import utcnow, generate_license_code, hash_license
import config
from services import subscription as sub_svc

logger = logging.getLogger(__name__)

VALID_TRANSITIONS = {
    "pending": {"awaiting_receipt", "under_review", "approved", "rejected", "cancelled"},
    "awaiting_receipt": {"under_review", "rejected", "cancelled"},
    "under_review": {"approved", "rejected", "cancelled"},
    "approved": set(),
    "rejected": set(),
    "cancelled": set(),
}


async def create_payment_request(
    user_id: int,
    plan_id: int,
    method: str,
) -> Optional[int]:
    plan = await sub_svc.get_plan_by_id(plan_id)
    if not plan or not plan.get("enabled"):
        return None
    if method not in ("gift", "card"):
        return None
    amount = int(plan["price"])
    row = await db.fetchrow(
        """
        INSERT INTO payment_requests
            (user_id, plan_id, plan_key, plan_name, method, status, amount, currency)
        VALUES ($1, $2, $3, $4, $5, 'pending', $6, 'IRR')
        RETURNING id
        """,
        user_id,
        plan["id"],
        plan["slug"],
        plan["name"],
        method,
        amount,
    )
    return row["id"] if row else None


async def get_payment(payment_id: int) -> Optional[dict]:
    row = await db.fetchrow("SELECT * FROM payment_requests WHERE id = $1", payment_id)
    return dict(row) if row else None


async def transition_payment(
    payment_id: int,
    new_status: str,
    admin_note: Optional[str] = None,
    receipt_file_id: Optional[str] = None,
) -> Tuple[bool, str]:
    async with db.transaction() as conn:
        row = await conn.fetchrow(
            "SELECT status FROM payment_requests WHERE id = $1 FOR UPDATE",
            payment_id,
        )
        if not row:
            return False, "درخواست یافت نشد."
        current = row["status"]
        allowed = VALID_TRANSITIONS.get(current, set())
        if new_status not in allowed:
            return False, f"انتقال وضعیت از {current} به {new_status} مجاز نیست."
        await conn.execute(
            """
            UPDATE payment_requests SET
                status = $2,
                admin_note = COALESCE($3, admin_note),
                receipt_file_id = COALESCE($4, receipt_file_id),
                updated_at = NOW()
            WHERE id = $1
            """,
            payment_id, new_status, admin_note, receipt_file_id,
        )
    return True, "ok"


async def create_license_for_payment(
    payment_id: int,
    user_id: int,
    plan_key: str,
    plan_id: Optional[int] = None,
) -> Optional[str]:
    code = generate_license_code()
    code_h = hash_license(code)
    expires = utcnow() + timedelta(hours=config.LICENSE_EXPIRE_HOURS)
    try:
        async with db.transaction() as conn:
            pay = await conn.fetchrow(
                "SELECT status, plan_id, plan_key FROM payment_requests WHERE id = $1 FOR UPDATE",
                payment_id,
            )
            if not pay or pay["status"] != "approved":
                return None
            existing = await conn.fetchval(
                "SELECT id FROM licenses WHERE payment_id = $1", payment_id
            )
            if existing:
                return None
            await conn.execute(
                """
                INSERT INTO licenses
                    (code_hash, code_plain, user_id, payment_id, plan_id, plan_key, status, expires_at)
                VALUES ($1, $2, $3, $4, $5, $6, 'active', $7)
                """,
                code_h, code, user_id, payment_id,
                plan_id or pay["plan_id"],
                plan_key or pay["plan_key"],
                expires,
            )
        return code
    except Exception as e:
        logger.exception("create_license failed: %s", e)
        return None


async def redeem_license(user_id: int, code: str) -> Tuple[bool, str]:
    if not code or len(code.strip()) < 8:
        return False, "❌ کد لایسنس معتبر نیست."
    code_h = hash_license(code.strip())

    async with db.transaction() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM licenses WHERE code_hash = $1 FOR UPDATE",
            code_h,
        )
        if not row:
            return False, "❌ کد لایسنس معتبر نیست."
        if row["status"] == "used":
            return False, "❌ این لایسنس قبلاً استفاده شده است."
        if row["status"] == "revoked":
            return False, "❌ این لایسنس لغو شده و فاقد اعتبار است."
        if row["status"] == "expired":
            return False, "❌ مهلت استفاده از این لایسنس به پایان رسیده است."
        if row["status"] == "cancelled":
            return False, "❌ این لایسنس لغو شده و فاقد اعتبار است."
        if row["status"] != "active":
            return False, "❌ این لایسنس نامعتبر است."
        if row["user_id"] != user_id:
            return False, "❌ این لایسنس متعلق به حساب دیگری است."
        if row["expires_at"] and row["expires_at"] < utcnow():
            await conn.execute(
                "UPDATE licenses SET status = 'expired' WHERE id = $1", row["id"]
            )
            return False, "❌ مهلت استفاده از این لایسنس به پایان رسیده است."

        plan = None
        if row["plan_id"]:
            plan = await conn.fetchrow("SELECT * FROM plans WHERE id = $1", row["plan_id"])
        if not plan and row["payment_id"]:
            pay = await conn.fetchrow(
                "SELECT * FROM payment_requests WHERE id = $1", row["payment_id"]
            )
            if pay and pay.get("plan_id"):
                plan = await conn.fetchrow("SELECT * FROM plans WHERE id = $1", pay["plan_id"])
        if not plan:
            plan = {
                "id": row["plan_id"],
                "slug": row["plan_key"],
                "name": row["plan_key"],
                "duration_days": 30,
            }

        await conn.execute(
            """
            UPDATE licenses SET
                status = 'used', used_at = NOW(), used_by = $2, code_plain = NULL
            WHERE id = $1
            """,
            row["id"], user_id,
        )
        now = utcnow()
        expires = now + timedelta(days=int(plan.get("duration_days") or 30))
        await conn.execute(
            "UPDATE subscriptions SET status = 'expired' WHERE user_id = $1 AND status = 'active'",
            user_id,
        )
        await conn.execute(
            """
            INSERT INTO subscriptions
                (user_id, plan_id, plan_key, plan_name, started_at, expires_at,
                 status, payment_method, payment_id, license_id)
            VALUES ($1, $2, $3, $4, $5, $6, 'active', 'license', $7, $8)
            """,
            user_id,
            plan.get("id"),
            plan.get("slug") or row["plan_key"],
            plan.get("name") or row["plan_key"],
            now, expires,
            row["payment_id"], row["id"],
        )

    return True, (
        f"✅ کد صحیح است!\n\n"
        f"اشتراک VIP «{plan.get('name') or row['plan_key']}» فعال شد.\n\n"
        f"وضعیت: 🟢 فعال"
    )


async def get_card_settings() -> Tuple[str, str]:
    num = await db.fetchval("SELECT value FROM system_settings WHERE key = 'card_number'")
    holder = await db.fetchval("SELECT value FROM system_settings WHERE key = 'card_holder'")
    return num or config.CARD_NUMBER, holder or config.CARD_HOLDER


async def set_card_settings(card_number: str, card_holder: str | None = None) -> None:
    card_number = (card_number or "").strip()
    await db.execute(
        """
        INSERT INTO system_settings (key, value, updated_at) VALUES ('card_number', $1, NOW())
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
        """,
        card_number,
    )
    if card_holder is not None:
        await db.execute(
            """
            INSERT INTO system_settings (key, value, updated_at) VALUES ('card_holder', $1, NOW())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """,
            card_holder.strip(),
        )


async def revoke_license(license_id: int, admin_id: int | None = None) -> Tuple[bool, str]:
    """Invalidate a license so it cannot be redeemed."""
    row = await db.fetchrow("SELECT * FROM licenses WHERE id = $1", int(license_id))
    if not row:
        return False, "لایسنس یافت نشد."
    if row["status"] == "revoked":
        return False, "این لایسنس از قبل لغو شده است."
    if row["status"] == "used":
        # still mark revoked for audit; subscription not auto-killed
        await db.execute(
            "UPDATE licenses SET status = 'revoked' WHERE id = $1",
            int(license_id),
        )
        return True, (
            f"لایسنس #{license_id} لغو شد (قبلاً استفاده شده بود).\n"
            "اشتراک فعال کاربر جداگانه قابل قطع است."
        )
    await db.execute(
        "UPDATE licenses SET status = 'revoked' WHERE id = $1",
        int(license_id),
    )
    return True, f"✅ لایسنس #{license_id} لغو و فاقد اعتبار شد."
