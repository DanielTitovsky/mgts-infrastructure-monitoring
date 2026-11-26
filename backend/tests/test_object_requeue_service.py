from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy.dialects import postgresql

from app.core.errors import AppError
from app.services.object_service import requeue_object


def object_row(**overrides):
    values = {
        "id": 23,
        "img_key": "objects/23/photo.jpg",
        "processing_status": "done",
        "processing_started_at": datetime.now(timezone.utc),
        "processing_attempts": 3,
        "processing_error": "previous error",
        "processed_at": datetime.now(timezone.utc),
        "processed_img_url": "/uploads/processed/obj_23.jpg",
        "status_id": 41,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class ObjectRequeueServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.obj = object_row()
        self.session = SimpleNamespace(
            scalar=AsyncMock(return_value=self.obj),
            commit=AsyncMock(),
            refresh=AsyncMock(),
        )

    async def test_requeues_one_photo_under_a_row_lock_and_preserves_existing_results(self) -> None:
        result = await requeue_object(self.session, 23)

        self.assertIs(result, self.obj)
        self.assertEqual(self.obj.processing_status, "awaiting_processing")
        self.assertIsNone(self.obj.processing_started_at)
        self.assertEqual(self.obj.processing_attempts, 0)
        self.assertIsNone(self.obj.processing_error)
        self.assertEqual(self.obj.processed_img_url, "/uploads/processed/obj_23.jpg")
        self.assertEqual(self.obj.status_id, 41)
        self.session.commit.assert_awaited_once()
        self.session.refresh.assert_awaited_once_with(self.obj)
        statement = self.session.scalar.await_args.args[0]
        self.assertIn("FOR UPDATE", str(statement.compile(dialect=postgresql.dialect())))

    async def test_rejects_an_active_job_without_mutation_or_commit(self) -> None:
        self.obj.processing_status = "processing"

        with self.assertRaises(AppError) as raised:
            await requeue_object(self.session, 23)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.obj.processing_status, "processing")
        self.session.commit.assert_not_awaited()

    async def test_rejects_missing_or_unsupported_photo_keys(self) -> None:
        for img_key in (None, "", "https://example.invalid/photo.jpg", "objects/24/photo.jpg"):
            with self.subTest(img_key=img_key):
                self.session.commit.reset_mock()
                self.session.scalar.return_value = object_row(img_key=img_key)
                with self.assertRaises(AppError) as raised:
                    await requeue_object(self.session, 23)
                self.assertEqual(raised.exception.status_code, 409)
                self.session.commit.assert_not_awaited()

    async def test_accepts_legacy_upload_paths(self) -> None:
        self.session.scalar.return_value = object_row(img_key="/uploads/raw/photo.jpg")

        result = await requeue_object(self.session, 23)

        self.assertEqual(result.processing_status, "awaiting_processing")
        self.session.commit.assert_awaited_once()

    async def test_rejects_unknown_object(self) -> None:
        self.session.scalar.return_value = None

        with self.assertRaises(AppError) as raised:
            await requeue_object(self.session, 23)

        self.assertEqual(raised.exception.status_code, 404)
        self.session.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
