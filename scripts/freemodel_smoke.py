#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Mapping


SUBMODULE_ROOT = Path(__file__).resolve().parents[1]
if str(SUBMODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(SUBMODULE_ROOT))


def _ok(label: str, detail: str = "") -> None:
    suffix = f" -> {detail}" if detail else ""
    print(f"[OK] {label}{suffix}")


def _fail(label: str, detail: str) -> None:
    print(f"[FAIL] {label} -> {detail}")


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
    return Path(__file__).resolve().parents[3]


def _submodule_root_from_here() -> Path:
    return Path(__file__).resolve().parents[1]


def _bindings_db_path(config: Mapping[str, str]) -> Path:
    return Path(
        config.get("bindings_db")
        or config.get("AI_HARNESS_BINDINGS_DB")
        or os.environ.get("AI_HARNESS_BINDINGS_DB")
        or _repo_root_from_here() / "data" / "provider-bindings.sqlite"
    )


def _init_bindings_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as con:
        con.executescript(
            """
            create table if not exists provider_telegram_bindings (
              id integer primary key autoincrement,
              provider text not null,
              provider_account_ref text,
              telegram_id text not null,
              start_code text not null,
              start_link text not null,
              status text not null,
              bot_response_status text,
              bot_response_text text,
              ss_panel_response_json text,
              error text,
              executor text,
              run_id text,
              created_at text not null default current_timestamp,
              updated_at text not null default current_timestamp,
              activated_at text
            );
            """
        )


def run_smoke_check(config: Mapping[str, str] | None = None) -> int:
    config = dict(config or {})
    failures: list[str] = []

    try:
        from platforms.freemodel.core import extract_freemodel_start_code
        from platforms.freemodel.plugin import FreemodelPlatform

        assert extract_freemodel_start_code("https://t.me/FreeModelDevBot?start=smoke") == "smoke"
        assert FreemodelPlatform.name == "freemodel"
        _ok("FreeModel platform import", "freemodel")
    except Exception as exc:
        failures.append("FreeModel platform import")
        _fail("FreeModel platform import", str(exc))

    try:
        from core.base_mailbox import MAILBOX_FACTORY_REGISTRY
        from providers.mailbox.proton_harness import ProtonHarnessMailbox

        aliases = config.get("proton_aliases") or config.get("PROTON_ALIASES") or "smoke@example.com"
        mailbox = ProtonHarnessMailbox.from_config({"proton_aliases": aliases})
        assert mailbox.get_email().email
        assert "proton_harness" in MAILBOX_FACTORY_REGISTRY
        _ok("Proton Harness mailbox config", "alias configured")
    except Exception as exc:
        failures.append("Proton Harness mailbox config")
        _fail("Proton Harness mailbox config", str(exc))

    try:
        from core.base_sms import create_sms_provider
        from providers.sms.sspanel_harness import SSPanelHarnessTelegramProvider

        provider = create_sms_provider(
            "sspanel_harness",
            {
                "sspanel_base_url": config.get("sspanel_base_url") or config.get("SSPANEL_BASE_URL") or "http://127.0.0.1:3000",
                "sspanel_admin_token": config.get("sspanel_admin_token") or config.get("SSPANEL_ADMIN_TOKEN") or "smoke-token",
                "bindings_db": str(_bindings_db_path(config)),
                "provider_bindings_script": str(_repo_root_from_here() / "scripts" / "provider-bindings"),
            },
        )
        assert isinstance(provider, SSPanelHarnessTelegramProvider)
        _ok("SSPanel Harness Telegram config", "provider ready")
    except Exception as exc:
        failures.append("SSPanel Harness Telegram config")
        _fail("SSPanel Harness Telegram config", str(exc))

    try:
        db_path = _bindings_db_path(config)
        _init_bindings_db(db_path)
        with sqlite3.connect(db_path) as con:
            con.execute("select 1 from provider_telegram_bindings limit 1").fetchall()
        _ok("provider-bindings database", str(db_path))
    except Exception as exc:
        failures.append("provider-bindings database")
        _fail("provider-bindings database", str(exc))

    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-check FreeModel HPE local wiring without live account provisioning")
    parser.add_argument("--config-json", default="", help="Optional JSON object with non-secret runtime settings")
    parser.add_argument("--env-file", default="", help="Optional env file; secrets are used but never printed")
    args = parser.parse_args(argv)

    config: dict[str, str] = {}
    config.update(_read_env_file(args.env_file))
    if args.config_json:
        loaded = json.loads(args.config_json)
        if not isinstance(loaded, dict):
            raise ValueError("--config-json must be a JSON object")
        config.update({str(key): str(value) for key, value in loaded.items()})
    return run_smoke_check(config)


if __name__ == "__main__":
    raise SystemExit(main())
