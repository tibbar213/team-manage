import sqlite3
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine as real_create_async_engine
import sqlalchemy.ext.asyncio as sqlalchemy_asyncio

_original_create_async_engine = sqlalchemy_asyncio.create_async_engine
sqlalchemy_asyncio.create_async_engine = lambda *args, **kwargs: None

from app.database import Base
from app.db_migrations import repair_warranty_timestamps
from app.models import RedemptionCode, Team
from app.services.redeem_flow import RedeemFlowService
from app.services.warranty import WarrantyService
from app.utils.time_utils import get_now

sqlalchemy_asyncio.create_async_engine = _original_create_async_engine


def _discard_task(coro):
    coro.close()
    return None


class WarrantyIssue20Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = real_create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_repeated_warranty_redemption_preserves_original_timestamps(self):
        async with self.session_factory() as session:
            first_team = Team(
                email="owner1@example.com",
                access_token_encrypted="enc",
                account_id="acct-1",
                team_name="Team One",
                current_members=0,
                max_members=6,
                status="active",
            )
            second_team = Team(
                email="owner2@example.com",
                access_token_encrypted="enc",
                account_id="acct-2",
                team_name="Team Two",
                current_members=0,
                max_members=6,
                status="active",
            )
            code = RedemptionCode(
                code="WARRANTY20",
                status="unused",
                has_warranty=True,
                warranty_days=30,
            )
            session.add_all([first_team, second_team, code])
            await session.commit()

            service = RedeemFlowService()
            service.select_team_auto = AsyncMock(return_value={"success": True, "team_id": first_team.id, "error": None})
            service.team_service.sync_team_info = AsyncMock(return_value={"success": True, "member_emails": []})
            service.team_service.ensure_access_token = AsyncMock(return_value="token")
            service.chatgpt_service.send_invite = AsyncMock(
                return_value={"success": True, "data": {"account_invites": [{"email": "user@example.com"}]}}
            )

            with patch("app.services.redeem_flow.asyncio.create_task", new=_discard_task):
                first_result = await service.redeem_and_join_team(
                    email="user@example.com",
                    code="WARRANTY20",
                    team_id=first_team.id,
                    db_session=session,
                )

            self.assertTrue(first_result["success"])

            first_code = await session.scalar(
                select(RedemptionCode).where(RedemptionCode.code == "WARRANTY20")
            )
            original_used_at = first_code.used_at
            original_expiry = first_code.warranty_expires_at

            self.assertIsNotNone(original_used_at)
            self.assertEqual(original_expiry, original_used_at + timedelta(days=30))

            first_team.status = "banned"
            second_team.status = "active"
            await session.commit()

            with patch("app.services.redeem_flow.asyncio.create_task", new=_discard_task):
                second_result = await service.redeem_and_join_team(
                    email="user@example.com",
                    code="WARRANTY20",
                    team_id=second_team.id,
                    db_session=session,
                )

            self.assertTrue(second_result["success"])

            updated_code = await session.scalar(
                select(RedemptionCode).where(RedemptionCode.code == "WARRANTY20")
            )
            self.assertEqual(updated_code.used_at, original_used_at)
            self.assertEqual(updated_code.warranty_expires_at, original_expiry)

    async def test_warranty_status_falls_back_to_first_redemption_record(self):
        async with self.session_factory() as session:
            team = Team(
                email="owner@example.com",
                access_token_encrypted="enc",
                account_id="acct-main",
                team_name="Main Team",
                current_members=0,
                max_members=6,
                status="banned",
            )
            code = RedemptionCode(
                code="WARRANTY-CHECK",
                status="used",
                has_warranty=True,
                warranty_days=30,
                used_at=None,
                warranty_expires_at=None,
            )
            session.add_all([team, code])
            await session.flush()

            first_redeem_at = get_now() - timedelta(days=12)
            second_redeem_at = get_now() - timedelta(days=2)
            from app.models import RedemptionRecord

            session.add_all(
                [
                    RedemptionRecord(
                        email="user@example.com",
                        code="WARRANTY-CHECK",
                        team_id=team.id,
                        account_id=team.account_id,
                        redeemed_at=first_redeem_at,
                        is_warranty_redemption=True,
                    ),
                    RedemptionRecord(
                        email="user@example.com",
                        code="WARRANTY-CHECK",
                        team_id=team.id,
                        account_id=team.account_id,
                        redeemed_at=second_redeem_at,
                        is_warranty_redemption=True,
                    ),
                ]
            )
            await session.commit()

            service = WarrantyService()
            result = await service.check_warranty_status(session, code="WARRANTY-CHECK")

            self.assertTrue(result["success"])
            self.assertEqual(
                result["warranty_expires_at"],
                (first_redeem_at + timedelta(days=30)).isoformat(),
            )

    def test_repair_warranty_timestamps_uses_first_redemption_record(self):
        conn = sqlite3.connect(":memory:")
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE redemption_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                has_warranty BOOLEAN DEFAULT 0,
                warranty_days INTEGER DEFAULT 30,
                used_at DATETIME,
                warranty_expires_at DATETIME
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE redemption_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                redeemed_at DATETIME
            )
            """
        )

        cursor.execute(
            """
            INSERT INTO redemption_codes (code, has_warranty, warranty_days, used_at, warranty_expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("FIXME20", 1, 30, "2026-03-10 10:00:00", "2026-04-09 10:00:00"),
        )
        cursor.executemany(
            """
            INSERT INTO redemption_records (code, redeemed_at)
            VALUES (?, ?)
            """,
            [
                ("FIXME20", "2026-03-01 08:00:00"),
                ("FIXME20", "2026-03-10 10:00:00"),
            ],
        )

        repaired = repair_warranty_timestamps(cursor)
        conn.commit()

        self.assertEqual(repaired, 1)

        cursor.execute(
            "SELECT used_at, warranty_expires_at FROM redemption_codes WHERE code = ?",
            ("FIXME20",),
        )
        used_at, warranty_expires_at = cursor.fetchone()
        self.assertEqual(used_at, "2026-03-01 08:00:00")
        self.assertEqual(warranty_expires_at, "2026-03-31 08:00:00")
        conn.close()


if __name__ == "__main__":
    unittest.main()
