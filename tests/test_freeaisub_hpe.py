from __future__ import annotations

import json
from types import SimpleNamespace
import pytest

from core.base_platform import Account, AccountStatus, RegisterConfig


def test_freeaisub_platform_maps_result_to_account():
    from platforms.freeaisub.plugin import FreeaisubPlatform

    platform = FreeaisubPlatform(RegisterConfig(executor_type="headed"))
    result = platform._map_freeaisub_result(
        {
            "email": "",
            "telegram": {
                "telegram_id": "8137700718",
                "status": "success",
                "start_link": "https://t.me/freeaisub_bot?start=e2f59b99d1",
            },
        }
    )

    assert result.user_id == "8137700718"
    assert result.token == "8137700718"
    assert result.extra["telegram_binding"]["telegram_id"] == "8137700718"


def test_freeaisub_register_referral_calls_sspanel_and_records(monkeypatch, tmp_path):
    from platforms.freeaisub.plugin import FreeaisubPlatform

    calls: list[tuple[str, object]] = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(("run", cmd))
        if "exclude" in cmd:
            return SimpleNamespace(returncode=0, stdout='["111","222"]\n', stderr="")
        if "record" in cmd:
            return SimpleNamespace(returncode=0, stdout='{"ok": true, "status": "success"}', stderr="")
        raise AssertionError(cmd)

    class FakeResponse:
        def __init__(self, data):
            self._data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self._data

    def fake_post(url, **kwargs):
        calls.append(("post", {"url": url, **kwargs}))
        return FakeResponse(
            {
                "results": [
                    {
                        "telegramId": "8137700718",
                        "code": "e2f59b99d1",
                        "botResponseStatus": "success",
                        "botResponseText": "Profile registered.",
                    }
                ]
            }
        )

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("requests.post", fake_post)

    platform = FreeaisubPlatform(
        RegisterConfig(
            executor_type="headed",
            extra={
                "sspanel_base_url": "http://sspanel.test",
                "sspanel_admin_token": "token",
                "bindings_db": str(tmp_path / "bindings.sqlite"),
                "provider_bindings_script": str(tmp_path / "provider-bindings"),
                "executor": "pytest",
            }
        )
    )

    result = platform.execute_action(
        "register_referral",
        Account(platform="freeaisub", email="", password="", user_id=""),
        {"referral_code": "e2f59b99d1", "provider_account_ref": "campaign_owner"}
    )

    assert result["ok"] is True
    assert result["data"]["status"] == "success"
    assert result["data"]["telegram_id"] == "8137700718"

    post_payload = next(value for kind, value in calls if kind == "post")
    assert post_payload["json"]["excludeTelegramIds"] == ["111", "222"]
    assert post_payload["json"]["botLink"] == "https://t.me/freeaisub_bot?start=e2f59b99d1"


def test_freeaisub_checkin_calls_sspanel_with_messages_and_records(monkeypatch, tmp_path):
    from platforms.freeaisub.plugin import FreeaisubPlatform

    calls: list[tuple[str, object]] = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(("run", cmd))
        if "exclude" in cmd:
            # Возвращаем список исключений, включая наш целевой ID
            # Но core.py должен вырезать его из списка перед отправкой в SSPanel
            return SimpleNamespace(returncode=0, stdout='["111","8137700718"]\n', stderr="")
        if "record" in cmd:
            return SimpleNamespace(returncode=0, stdout='{"ok": true, "status": "success"}', stderr="")
        raise AssertionError(cmd)

    class FakeResponse:
        def __init__(self, data):
            self._data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self._data

    def fake_post(url, **kwargs):
        calls.append(("post", {"url": url, **kwargs}))
        return FakeResponse(
            {
                "results": [
                    {
                        "telegramId": "8137700718",
                        "botResponseStatus": "success",
                        "botResponseText": "Check-in successful.",
                    }
                ]
            }
        )

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("requests.post", fake_post)

    platform = FreeaisubPlatform(
        RegisterConfig(
            executor_type="headed",
            extra={
                "sspanel_base_url": "http://sspanel.test",
                "sspanel_admin_token": "token",
                "bindings_db": str(tmp_path / "bindings.sqlite"),
                "provider_bindings_script": str(tmp_path / "provider-bindings"),
                "executor": "pytest",
            }
        )
    )

    result = platform.execute_action(
        "checkin",
        Account(platform="freeaisub", email="", password="", user_id="8137700718"),
        {"provider_account_ref": "daily_checkin"}
    )

    assert result["ok"] is True
    assert result["data"]["status"] == "success"

    post_payload = next(value for kind, value in calls if kind == "post")
    # Проверяем, что 8137700718 БЫЛ убран из excludeTelegramIds, чтобы sspanel выбрал именно его
    assert "8137700718" not in post_payload["json"]["excludeTelegramIds"]
    assert post_payload["json"]["excludeTelegramIds"] == ["111"]
    assert post_payload["json"]["botLink"] == "https://t.me/freeaisub_bot"
    assert post_payload["json"]["messages"] == ["/checkin"]
