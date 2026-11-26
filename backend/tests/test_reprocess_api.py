from __future__ import annotations

import base64
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.router import api_router
from app.core.config import settings
from app.core.errors import AppError, register_exception_handlers
from app.db.session import get_session
from app.services import object_service, user_service


class ObjectReprocessApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = SimpleNamespace(id=7, username="operator", role="admin")
        self.session = SimpleNamespace(get=AsyncMock(return_value=self.user))
        self.authenticate = AsyncMock(return_value=self.user)
        self.reprocess = AsyncMock(return_value=SimpleNamespace(
            id=23,
            type="support",
            external_id=None,
            place=None,
            lat=None,
            lon=None,
            status_id=None,
            img_url="/api/infrastructure-objects/23/photo",
            processed_img_url=None,
            processing_status="awaiting_processing",
            processing_error=None,
            processed_at=None,
        ))

        self.auth_setting = patch.object(settings, "auth_required", True)
        self.auth_setting.start()
        self.authenticate_patch = patch.object(user_service, "authenticate", self.authenticate)
        self.authenticate_patch.start()
        self.reprocess_patch = patch.object(object_service, "requeue_object", self.reprocess)
        self.reprocess_patch.start()

        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(api_router, prefix="/api")

        async def provide_session():
            yield self.session

        app.dependency_overrides[get_session] = provide_session
        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self) -> None:
        self.client.close()
        self.reprocess_patch.stop()
        self.authenticate_patch.stop()
        self.auth_setting.stop()

    @staticmethod
    def basic_header() -> str:
        return "Basic " + base64.b64encode(b"operator:secret").decode("ascii")

    def test_authenticated_request_requeues_only_the_path_object(self) -> None:
        response = self.client.post(
            "/api/infrastructure-objects/23/reprocess",
            headers={"Authorization": self.basic_header()},
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["data"]["processing_status"], "awaiting_processing")
        self.reprocess.assert_awaited_once_with(self.session, 23)

    def test_unauthenticated_request_does_not_requeue(self) -> None:
        response = self.client.post("/api/infrastructure-objects/23/reprocess")

        self.assertEqual(response.status_code, 401)
        self.reprocess.assert_not_awaited()

    def test_active_job_is_returned_as_conflict(self) -> None:
        self.reprocess.side_effect = AppError(409, "Объект уже обрабатывается", "Повторите позже.")

        response = self.client.post(
            "/api/infrastructure-objects/23/reprocess",
            headers={"Authorization": self.basic_header()},
        )

        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
