# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright==1.61.0"]
# ///
"""Text-only login/navigation smoke; no screenshots or dataset image inspection.

Run with uv run scripts/test-browser-smoke.py --help.
Credentials are supplied through MGTS_SMOKE_USERNAME/MGTS_SMOKE_PASSWORD.
Optional gateway credentials use MGTS_GATEWAY_USERNAME/MGTS_GATEWAY_PASSWORD.
"""
import argparse
import base64
import os
import re
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--browser-executable")
    args = parser.parse_args()
    url = urlparse(args.base_url)
    if url.scheme not in {"http", "https"} or url.username or url.password:
        parser.error("Use an HTTP(S) URL without embedded credentials")
    username = os.environ.get("MGTS_SMOKE_USERNAME")
    password = os.environ.get("MGTS_SMOKE_PASSWORD")
    if not username or not password:
        parser.error("Set MGTS_SMOKE_USERNAME and MGTS_SMOKE_PASSWORD")
    gateway_user = os.environ.get("MGTS_GATEWAY_USERNAME")
    gateway_password = os.environ.get("MGTS_GATEWAY_PASSWORD")
    if bool(gateway_user) != bool(gateway_password):
        parser.error("Set both gateway credential variables")
    options = {}
    if gateway_user:
        options["http_credentials"] = {"username": gateway_user, "password": gateway_password}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path=args.browser_executable
        )
        try:
            page = browser.new_page(**options)
            page.set_default_timeout(30000)
            response = page.goto(args.base_url.rstrip("/") + "/admin", wait_until="networkidle")
            assert response is not None and response.ok, "Login document unavailable"
            page.get_by_label("Имя пользователя", exact=True).fill(username)
            page.get_by_label("Пароль", exact=True).fill(password)
            page.get_by_role("button", name="Войти", exact=True).click()
            page.wait_for_url("**/admin/objects")
            expect(page.get_by_role("heading", name="Объекты", exact=True)).to_be_visible()
            for label, path in [("Дефекты", "findings"), ("Статусы", "statuses"),
                                ("Пользователи", "users"), ("Карта", "map"),
                                ("Объекты", "objects")]:
                page.get_by_role("navigation", name="Основная навигация").get_by_role(
                    "link", name=label, exact=True
                ).click()
                page.wait_for_url("**/admin/" + path)
                expect(page.get_by_role("heading", name=label, exact=True)).to_be_visible()
                print("PASS navigation", path)
            page.get_by_role("link", name="Добавить объект", exact=True).click()
            page.wait_for_url("**/admin/objects/action")
            expect(page.get_by_label("Тип объекта", exact=True)).to_be_visible()
            page.get_by_label("Тип объекта", exact=True).fill("smoke-not-saved")
            photo = page.get_by_label("Выберите фото объекта", exact=True)
            photo.set_input_files({"name": "invalid.txt", "mimeType": "text/plain", "buffer": b"not an image"})
            expect(page.get_by_text("Допустимы только изображения JPEG, PNG и WebP.").first).to_be_visible()
            # Synthetic one-pixel fixture: validate DOM/loading, never interpret pixels.
            photo.set_input_files({"name": "smoke.png", "mimeType": "image/png", "buffer": base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1sAAAAASUVORK5CYII="
            )})
            expect(page.get_by_text("Предпросмотр выбранного файла", exact=True)).to_be_visible()
            expect(page.get_by_role("img", name="Фото объекта", exact=True)).to_have_attribute("src", re.compile(r"^blob:"))
            page.get_by_role("button", name="Удалить фото", exact=True).click()
            expect(page.get_by_text("Фото не загружено", exact=True)).to_be_visible()
            print("PASS create form, photo validation/preview/removal (not saved)")
            page.get_by_role("button", name="Выйти", exact=True).click()
            page.wait_for_url("**/admin")
            expect(page.get_by_label("Имя пользователя", exact=True)).to_be_visible()
            assert not any(c["name"] == "token" and c["value"] for c in page.context.cookies())
            print("PASS login, navigation, logout (DOM only)")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
