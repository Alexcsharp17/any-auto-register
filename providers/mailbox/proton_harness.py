"""Proton Mail connector for ai-harness registration flows."""
from __future__ import annotations

import email
import imaplib
import os
import re
import time
from email.message import Message
from pathlib import Path

from core.base_mailbox import BaseMailbox, MailboxAccount
from providers.registry import register_provider


def _split_csv(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item or "").strip()]
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


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


def _message_text(message: Message) -> str:
    parts: list[str] = []
    for key in ("subject", "from", "to"):
        value = message.get(key, "")
        if value:
            decoded = email.header.decode_header(value)
            rendered = ""
            for chunk, charset in decoded:
                if isinstance(chunk, bytes):
                    rendered += chunk.decode(charset or "utf-8", errors="replace")
                else:
                    rendered += chunk
            parts.append(rendered)
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_maintype() == "multipart":
                continue
            payload = part.get_payload(decode=True)
            if payload:
                parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
    else:
        payload = message.get_payload(decode=True)
        if payload:
            parts.append(payload.decode(message.get_content_charset() or "utf-8", errors="replace"))
        else:
            parts.append(str(message.get_payload() or ""))
    return "\n".join(parts)


@register_provider("mailbox", "proton_harness")
class ProtonHarnessMailbox(BaseMailbox):
    """Read forwarded registration mail from Proton Bridge IMAP."""

    def __init__(
        self,
        *,
        imap_host: str = "127.0.0.1",
        imap_port: int = 1143,
        imap_user: str = "",
        imap_password: str = "",
        aliases: list[str] | tuple[str, ...] | str | None = None,
        mailbox: str = "INBOX",
        poll_interval: float = 3.0,
    ):
        self.imap_host = imap_host
        self.imap_port = int(imap_port or 1143)
        self.imap_user = imap_user
        self.imap_password = imap_password
        self.aliases = _split_csv(aliases)
        self.mailbox = mailbox or "INBOX"
        self.poll_interval = float(poll_interval or 3.0)
        self._alias_index = 0

    @classmethod
    def from_config(cls, config: dict) -> "ProtonHarnessMailbox":
        config = dict(config or {})
        env_values = _read_env_file(config.get("proton_env_file") or config.get("env_file"))
        merged = {**env_values, **config}
        return cls(
            imap_host=merged.get("proton_imap_host") or merged.get("PROTON_IMAP_HOST") or "127.0.0.1",
            imap_port=int(merged.get("proton_imap_port") or merged.get("PROTON_IMAP_PORT") or 1143),
            imap_user=merged.get("proton_imap_user") or merged.get("PROTON_IMAP_USER") or "",
            imap_password=merged.get("proton_imap_password") or merged.get("PROTON_IMAP_PASSWORD") or "",
            aliases=merged.get("proton_aliases") or merged.get("PROTON_ALIASES") or merged.get("relay_aliases") or "",
            mailbox=merged.get("proton_mailbox") or merged.get("PROTON_MAILBOX") or "INBOX",
        )

    def _connect(self):
        conn = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
        if self.imap_user or self.imap_password:
            conn.login(self.imap_user, self.imap_password)
        conn.select(self.mailbox)
        return conn

    def get_email(self) -> MailboxAccount:
        if not self.aliases:
            raise RuntimeError("ProtonHarnessMailbox requires at least one relay alias")
        alias = self.aliases[self._alias_index % len(self.aliases)]
        self._alias_index += 1
        return MailboxAccount(
            email=alias,
            account_id=alias,
            extra={
                "provider_account": {
                    "provider_type": "mailbox",
                    "provider_name": "proton_harness",
                    "login_identifier": self.imap_user,
                    "display_name": "Proton Harness",
                    "metadata": {"alias": alias},
                },
                "provider_resource": {
                    "provider_type": "mailbox",
                    "provider_name": "proton_harness",
                    "resource_type": "mailbox_alias",
                    "resource_identifier": alias,
                    "handle": alias,
                    "display_name": alias,
                },
            },
        )

    def get_current_ids(self, account: MailboxAccount) -> set:
        conn = self._connect()
        try:
            status, payload = conn.search(None, "ALL")
            if status != "OK" or not payload:
                return set()
            return {item.decode("utf-8") for item in payload[0].split() if item}
        finally:
            self._close(conn)

    def wait_for_code(
        self,
        account: MailboxAccount,
        keyword: str = "",
        timeout: int = 120,
        before_ids: set = None,
        code_pattern: str = None,
    ) -> str:
        seen = {str(item) for item in (before_ids or set())}
        deadline = time.time() + timeout
        pattern = re.compile(code_pattern or r"(?<!\d)(\d{6})(?!\d)")
        while time.time() < deadline:
            for message_id, text in self._new_messages(seen):
                seen.add(message_id)
                lowered = text.lower()
                if keyword and keyword.lower() not in lowered:
                    continue
                if "freemodel" in keyword.lower() and "hello@freemodel.dev" not in lowered and "freemodel" not in lowered:
                    continue
                match = pattern.search(text)
                if match:
                    return match.group(1) if match.groups() else match.group(0)
            time.sleep(self.poll_interval)
        raise TimeoutError(f"等待 Proton 验证码超时 ({timeout}s)")

    def _new_messages(self, seen: set[str]) -> list[tuple[str, str]]:
        conn = self._connect()
        try:
            status, payload = conn.search(None, "ALL")
            if status != "OK" or not payload:
                return []
            ids = [item for item in payload[0].split() if item]
            results: list[tuple[str, str]] = []
            for raw_id in reversed(ids):
                message_id = raw_id.decode("utf-8")
                if message_id in seen:
                    continue
                fetch_status, fetch_payload = conn.fetch(raw_id, "(RFC822)")
                if fetch_status != "OK":
                    continue
                for item in fetch_payload or []:
                    if not isinstance(item, tuple) or len(item) < 2:
                        continue
                    message = email.message_from_bytes(item[1])
                    results.append((message_id, _message_text(message)))
            return results
        finally:
            self._close(conn)

    @staticmethod
    def _close(conn) -> None:
        try:
            conn.close()
        except Exception:
            pass
        try:
            conn.logout()
        except Exception:
            pass
