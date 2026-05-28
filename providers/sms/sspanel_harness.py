"""SSPanel Telegram bot activation provider for ai-harness."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import requests

from core.base_sms import BaseSmsProvider, SmsActivation
from providers.registry import register_provider


def _read_env_file(path: str | os.PathLike | None) -> dict[str, str]:
    if not path:
        return {}
    env_path = Path(path)
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[4]


@dataclass
class TelegramBotActivationResult:
    provider: str
    start_link: str
    status: str
    telegram_id: str = ""
    start_code: str = ""
    bot_response_status: str = ""
    bot_response_text: str = ""
    raw_response: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "start_link": self.start_link,
            "status": self.status,
            "telegram_id": self.telegram_id,
            "start_code": self.start_code,
            "bot_response_status": self.bot_response_status,
            "bot_response_text": self.bot_response_text,
            "raw_response": self.raw_response,
        }


class HarnessBindingRecorder:
    """Shell adapter around ai-harness scripts/provider-bindings."""

    def __init__(self, *, script: str | os.PathLike | None = None, db_path: str | os.PathLike | None = None):
        self.script = Path(script) if script else _repo_root_from_here() / "scripts" / "provider-bindings"
        self.db_path = Path(db_path) if db_path else Path(os.environ.get("AI_HARNESS_BINDINGS_DB", "data/provider-bindings.sqlite"))

    def exclude_telegram_ids(self, provider: str) -> list[str]:
        cmd = [
            str(self.script),
            "--db",
            str(self.db_path),
            "exclude",
            "--provider",
            provider,
        ]
        completed = subprocess.run(cmd, text=True, capture_output=True, check=False)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "provider-bindings exclude failed")
        payload = completed.stdout.strip() or "[]"
        data = json.loads(payload)
        if not isinstance(data, list):
            raise RuntimeError("provider-bindings exclude returned non-list JSON")
        return [str(item) for item in data]

    def record(
        self,
        *,
        provider: str,
        provider_account_ref: str,
        start_link: str,
        response: dict,
        executor: str = "",
        run_id: str = "",
    ) -> dict:
        cmd = [
            str(self.script),
            "--db",
            str(self.db_path),
            "record",
            "--provider",
            provider,
            "--provider-account-ref",
            provider_account_ref,
            "--start-link",
            start_link,
            "--ss-panel-response-json",
            json.dumps(response, ensure_ascii=False),
        ]
        if executor:
            cmd.extend(["--executor", executor])
        if run_id:
            cmd.extend(["--run-id", run_id])
        completed = subprocess.run(cmd, text=True, capture_output=True, check=False)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "provider-bindings record failed")
        return json.loads(completed.stdout.strip() or "{}")

    def record_action(
        self,
        *,
        telegram_id: str,
        bot_username: str,
        action_type: str,
        status: str,
        payload: str | None = None,
        executor: str = "",
    ) -> dict:
        cmd = [
            str(self.script),
            "--db",
            str(self.db_path),
            "record-action",
            "--telegram-id",
            telegram_id,
            "--bot-username",
            bot_username,
            "--action-type",
            action_type,
            "--status",
            status,
        ]
        if payload:
            cmd.extend(["--payload", payload])
        if executor:
            cmd.extend(["--executor", executor])
        completed = subprocess.run(cmd, text=True, capture_output=True, check=False)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "provider-bindings record-action failed")
        return json.loads(completed.stdout.strip() or "{}")


@register_provider("sms", "sspanel_harness")
class SSPanelHarnessTelegramProvider(BaseSmsProvider):
    """Activate Telegram bot start links through the SSPanel account pool."""

    auto_report_success_on_code = False

    def __init__(
        self,
        *,
        base_url: str = "",
        admin_token: str = "",
        admin_email: str = "",
        admin_password: str = "",
        bindings_db: str | os.PathLike | None = None,
        provider_bindings_script: str | os.PathLike | None = None,
        executor: str = "",
        timeout: int = 30,
    ):
        self.base_url = str(base_url or "").rstrip("/")
        self.admin_token = str(admin_token or "").strip()
        self.admin_email = str(admin_email or "").strip()
        self.admin_password = str(admin_password or "").strip()
        self.executor = str(executor or os.environ.get("AI_HARNESS_EXECUTOR") or "any-auto-register").strip()
        self.timeout = int(timeout or 30)
        self.recorder = HarnessBindingRecorder(script=provider_bindings_script, db_path=bindings_db)

    @classmethod
    def from_config(cls, config: dict) -> "SSPanelHarnessTelegramProvider":
        config = dict(config or {})
        env_values = _read_env_file(config.get("sspanel_env_file") or config.get("env_file"))
        merged = {**env_values, **config}
        return cls(
            base_url=merged.get("sspanel_base_url") or merged.get("SSPANEL_BASE_URL") or "",
            admin_token=merged.get("sspanel_admin_token") or merged.get("SSPANEL_ADMIN_TOKEN") or "",
            admin_email=merged.get("sspanel_admin_email") or merged.get("SSPANEL_ADMIN_EMAIL") or "",
            admin_password=merged.get("sspanel_admin_password") or merged.get("SSPANEL_ADMIN_PASSWORD") or "",
            bindings_db=merged.get("bindings_db") or merged.get("AI_HARNESS_BINDINGS_DB") or None,
            provider_bindings_script=merged.get("provider_bindings_script") or "",
            executor=merged.get("executor") or merged.get("AI_HARNESS_EXECUTOR") or "",
            timeout=int(merged.get("sspanel_timeout") or 30),
        )

    def activate_bot_link(
        self,
        bot_link: str,
        *,
        provider: str,
        provider_account_ref: str = "",
        limit: int = 1,
        bot_response_wait_ms: int = 3000,
        dry_run: bool = False,
        run_id: str = "",
    ) -> TelegramBotActivationResult:
        if not self.base_url:
            raise RuntimeError("SSPanel base URL is not configured")
        exclude_ids = self.recorder.exclude_telegram_ids(provider)
        payload = {
            "botLink": bot_link,
            "limit": limit,
            "excludeTelegramIds": exclude_ids,
            "messages": [],
            "botResponseWaitMs": bot_response_wait_ms,
            "dryRun": dry_run,
        }
        response = requests.post(
            f"{self.base_url}/api/v2/telegram/bot-start/test",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._token()}",
            },
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        raw_response = response.json()
        record_result = self.recorder.record(
            provider=provider,
            provider_account_ref=provider_account_ref,
            start_link=bot_link,
            response=raw_response,
            executor=self.executor,
            run_id=run_id,
        )
        first = self._first_result(raw_response)
        return TelegramBotActivationResult(
            provider=provider,
            start_link=bot_link,
            status=str(record_result.get("status") or self._classify(first)),
            telegram_id=str(first.get("telegramId") or first.get("telegram_id") or ""),
            start_code=str(first.get("code") or first.get("start_code") or ""),
            bot_response_status=str(first.get("botResponseStatus") or ""),
            bot_response_text=str(first.get("botResponseText") or ""),
            raw_response=raw_response,
        )

    def _token(self) -> str:
        if self.admin_token:
            return self.admin_token
        if not self.admin_email or not self.admin_password:
            raise RuntimeError("SSPanel admin token or email/password is required")
        response = requests.post(
            f"{self.base_url}/api/v2/auth/login",
            headers={"Content-Type": "application/json"},
            json={"email": self.admin_email, "password": self.admin_password},
            timeout=self.timeout,
        )
        response.raise_for_status()
        token = str(response.json().get("token") or "").strip()
        if not token:
            raise RuntimeError("SSPanel auth response did not include token")
        self.admin_token = token
        return token

    @staticmethod
    def _first_result(response: dict) -> dict:
        results = response.get("results") if isinstance(response, dict) else None
        if isinstance(results, list) and results and isinstance(results[0], dict):
            return results[0]
        return response if isinstance(response, dict) else {}

    @staticmethod
    def _classify(result: dict) -> str:
        status = str(result.get("botResponseStatus") or "").lower()
        text = str(result.get("botResponseText") or "").lower()
        error = str(result.get("error") or result.get("message") or "").lower()
        if "senddirectmessage returned false" in error:
            return "send_failed"
        if "this binding link has expired" in text:
            return "expired"
        if "already bound to a different account" in text:
            return "failed"
        if status == "success" or "account bound successfully" in text:
            return "success"
        if status == "failed":
            return "failed"
        return "unknown"

    # BaseSmsProvider compatibility. Telegram activation uses activate_bot_link().
    def get_number(self, *, service: str, country: str = "") -> SmsActivation:
        parsed = urlparse(service)
        if parsed.scheme in {"http", "https", "tg"}:
            return SmsActivation(activation_id=service, phone_number=service, country=country)
        raise RuntimeError("SSPanelHarnessTelegramProvider expects activate_bot_link() with a Telegram bot link")

    def get_code(self, activation_id: str, *, timeout: int = 120) -> str:
        return ""

    def cancel(self, activation_id: str) -> bool:
        return True
