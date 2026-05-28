from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from core.base_mailbox import MailboxAccount
from core.base_platform import RegisterConfig


def test_freemodel_start_link_helpers_extract_token_and_reject_wrong_bot():
    from platforms.freemodel.core import extract_freemodel_start_code

    assert (
        extract_freemodel_start_code("https://t.me/FreeModelDevBot?start=iBHwRVAyZV3K")
        == "iBHwRVAyZV3K"
    )
    assert (
        extract_freemodel_start_code("tg://resolve?domain=FreeModelDevBot&start=abc-123")
        == "abc-123"
    )

    with pytest.raises(ValueError, match="FreeModelDevBot"):
        extract_freemodel_start_code("https://t.me/OtherBot?start=abc")


def test_freemodel_platform_maps_browser_result_to_account():
    from platforms.freemodel.plugin import FreemodelPlatform

    platform = FreemodelPlatform(RegisterConfig(executor_type="headed"))
    result = platform._map_freemodel_result(
        {
            "email": "alias@mozmail.com",
            "password": "pw",
            "api_key": "free-mod-key",
            "telegram": {
                "telegram_id": "12345",
                "status": "success",
                "start_link": "https://t.me/FreeModelDevBot?start=tok",
            },
        }
    )

    assert result.email == "alias@mozmail.com"
    assert result.token == "free-mod-key"
    assert result.extra["api_key"] == "free-mod-key"
    assert result.extra["telegram_binding"]["telegram_id"] == "12345"


def test_proton_harness_mailbox_extracts_latest_freemodel_code(monkeypatch):
    from providers.mailbox.proton_harness import ProtonHarnessMailbox

    class FakeIMAP:
        def __init__(self, host, port):
            self.host = host
            self.port = port

        def login(self, username, password):
            self.username = username

        def select(self, mailbox):
            return "OK", [b"2"]

        def search(self, charset, criterion):
            return "OK", [b"1 2"]

        def fetch(self, message_id, query):
            messages = {
                b"1": b"Subject: Old mail\r\nFrom: nobody@example.com\r\n\r\nNothing",
                b"2": (
                    b"Subject: Your FreeModel code: 908056\r\n"
                    b"From: hello@freemodel.dev\r\n\r\n908056"
                ),
            }
            return "OK", [(b"RFC822", messages[message_id])]

        def close(self):
            pass

        def logout(self):
            pass

    monkeypatch.setattr("imaplib.IMAP4_SSL", FakeIMAP)

    mailbox = ProtonHarnessMailbox(
        imap_host="127.0.0.1",
        imap_port=1143,
        imap_user="bridge-user",
        imap_password="bridge-pass",
        aliases=["alias@mozmail.com"],
    )

    account = mailbox.get_email()

    assert account.email == "alias@mozmail.com"
    assert mailbox.get_current_ids(account) == {"1", "2"}
    assert mailbox.wait_for_code(
        account,
        keyword="FreeModel",
        before_ids={"1"},
        timeout=1,
    ) == "908056"


def test_sspanel_harness_uses_exclude_ids_and_records_binding(monkeypatch, tmp_path):
    from providers.sms.sspanel_harness import SSPanelHarnessTelegramProvider

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
                        "telegramId": "333",
                        "code": "tok",
                        "botResponseStatus": "success",
                        "botResponseText": "Account bound successfully.",
                    }
                ]
            }
        )

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("requests.post", fake_post)

    provider = SSPanelHarnessTelegramProvider(
        base_url="http://sspanel.test",
        admin_token="token",
        bindings_db=tmp_path / "bindings.sqlite",
        provider_bindings_script=tmp_path / "provider-bindings",
        executor="pytest",
    )

    result = provider.activate_bot_link(
        "https://t.me/FreeModelDevBot?start=tok",
        provider="freemodel",
        provider_account_ref="alias@mozmail.com",
        bot_response_wait_ms=50,
    )

    assert result.status == "success"
    post_payload = next(value for kind, value in calls if kind == "post")
    assert post_payload["json"]["excludeTelegramIds"] == ["111", "222"]
    assert post_payload["json"]["botLink"] == "https://t.me/FreeModelDevBot?start=tok"
    record_cmd = next(cmd for kind, cmd in calls if kind == "run" and "record" in cmd)
    assert "--provider-account-ref" in record_cmd
    assert "alias@mozmail.com" in record_cmd
    assert "--ss-panel-response-json" in record_cmd
    assert json.loads(record_cmd[record_cmd.index("--ss-panel-response-json") + 1])["results"][0]["telegramId"] == "333"


def test_freemodel_smoke_check_validates_local_wiring_without_secrets(tmp_path, capsys):
    from scripts.freemodel_smoke import run_smoke_check

    result = run_smoke_check(
        {
            "bindings_db": str(tmp_path / "provider-bindings.sqlite"),
            "proton_aliases": "alias@mozmail.com",
            "sspanel_base_url": "http://sspanel.test",
            "sspanel_admin_token": "test-token",
        }
    )

    captured = capsys.readouterr().out
    assert result == 0
    assert "FreeModel platform import" in captured
    assert "Proton Harness mailbox config" in captured
    assert "SSPanel Harness Telegram config" in captured
    assert "provider-bindings database" in captured
    assert "test-token" not in captured
