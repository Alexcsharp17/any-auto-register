"""freeaisub (智联 free ai) platform plugin."""
from __future__ import annotations

from core.base_mailbox import BaseMailbox
from core.base_platform import Account, AccountStatus, BasePlatform, RegisterConfig
from core.registration import RegistrationResult
from core.registry import register
from platforms.freeaisub.core import FreeaisubHarness, FREEAISUB_BOT_LINK


@register
class FreeaisubPlatform(BasePlatform):
    name = "freeaisub"
    display_name = "freeaisub"
    version = "0.1.0"
    supported_executors = ["headless", "headed"]  # Для совместимости, хотя по сути это Telegram-only
    supported_identity_modes = ["mailbox"]
    capabilities = ["query_state"]

    def __init__(self, config: RegisterConfig = None, mailbox: BaseMailbox = None):
        super().__init__(config)
        self.mailbox = mailbox

    def _map_freeaisub_result(self, result: dict) -> RegistrationResult:
        telegram = dict(result.get("telegram") or result.get("telegram_binding") or {})
        return RegistrationResult(
            email=str(result.get("email") or ""),
            password="",
            user_id=str(telegram.get("telegram_id") or ""),
            token=str(telegram.get("telegram_id") or ""),
            status=AccountStatus.REGISTERED,
            extra={
                "telegram_binding": telegram,
                "bot_link": FREEAISUB_BOT_LINK,
            },
        )

    def check_valid(self, account: Account) -> bool:
        # Для Telegram-аккаунта валидность проверяется статусом в БД или ответом бота
        tg_binding = account.extra.get("telegram_binding") or {}
        return tg_binding.get("status") == "success"

    def get_quota(self, account: Account) -> dict:
        return {
            "provider": self.name,
            "bot_link": FREEAISUB_BOT_LINK,
            "telegram_id": account.user_id,
            "status": account.status.value,
            "telegram_status": (account.extra or {}).get("telegram_binding", {}).get("status", ""),
        }

    def get_platform_actions(self) -> list:
        return [
            {
                "id": "checkin",
                "label": "Ежедневный Check-In",
                "params": [
                    {"key": "provider_account_ref", "label": "Идентификатор кампании", "type": "string"}
                ],
            },
            {
                "id": "register_referral",
                "label": "Регистрация реферала",
                "params": [
                    {"key": "referral_code", "label": "Реферальный код", "type": "string"},
                    {"key": "provider_account_ref", "label": "Идентификатор кампании", "type": "string"},
                ],
            },
        ]

    def execute_action(self, action_id: str, account: Account, params: dict) -> dict:
        harness = FreeaisubHarness(self.config.extra, log_fn=self.log)
        
        if action_id == "checkin":
            ref = str(params.get("provider_account_ref") or "daily_checkin")
            result = harness.checkin(
                telegram_id=account.user_id,
                provider_account_ref=ref,
            )
            return {
                "ok": result.status == "success",
                "data": result.to_dict(),
                "error": result.bot_response_text if result.status != "success" else None,
            }
            
        elif action_id == "register_referral":
            code = params.get("referral_code")
            ref = params.get("provider_account_ref") or "campaign_owner"
            result = harness.register_referral(
                referral_code=code,
                provider_account_ref=ref,
            )
            return {
                "ok": result.status == "success",
                "data": result.to_dict(),
                "error": result.bot_response_text if result.status != "success" else None,
            }

        raise NotImplementedError(f"Действие '{action_id}' не поддерживается платформой freeaisub")
