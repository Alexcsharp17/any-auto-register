"""FreeModel platform plugin."""
from __future__ import annotations

from core.base_mailbox import BaseMailbox
from core.base_platform import Account, AccountStatus, BasePlatform, RegisterConfig
from core.registration import BrowserRegistrationAdapter, OtpSpec, RegistrationResult
from core.registration.helpers import resolve_timeout
from core.registry import register
from platforms.freemodel.core import FREEMODEL_API_BASE


@register
class FreemodelPlatform(BasePlatform):
    name = "freemodel"
    display_name = "FreeModel"
    version = "0.1.0"
    supported_executors = ["headless", "headed"]
    supported_identity_modes = ["mailbox"]
    capabilities = ["query_state"]

    def __init__(self, config: RegisterConfig = None, mailbox: BaseMailbox = None):
        super().__init__(config)
        self.mailbox = mailbox

    def _map_freemodel_result(self, result: dict) -> RegistrationResult:
        api_key = str(result.get("api_key") or result.get("token") or "").strip()
        telegram = dict(result.get("telegram") or result.get("telegram_binding") or {})
        return RegistrationResult(
            email=str(result.get("email") or ""),
            password=str(result.get("password") or ""),
            user_id=str(result.get("user_id") or ""),
            token=api_key,
            status=AccountStatus.REGISTERED,
            extra={
                "api_key": api_key,
                "api_base": FREEMODEL_API_BASE,
                "telegram_binding": telegram,
                "dashboard_url": result.get("dashboard_url", ""),
            },
        )

    def build_browser_registration_adapter(self):
        def _build_worker(ctx, artifacts):
            from platforms.freemodel.browser_register import FreemodelBrowserRegister
            from providers.sms.sspanel_harness import SSPanelHarnessTelegramProvider

            telegram_provider = None
            if str(ctx.extra.get("telegram_provider") or "sspanel_harness") == "sspanel_harness":
                telegram_provider = SSPanelHarnessTelegramProvider.from_config(ctx.extra)

            return FreemodelBrowserRegister(
                headless=(ctx.executor_type == "headless"),
                proxy=ctx.proxy,
                otp_callback=artifacts.otp_callback,
                telegram_provider=telegram_provider,
                log_fn=ctx.log,
                browser_engine=str(ctx.extra.get("browser_engine") or "auto"),
                user_data_dir=str(ctx.extra.get("chrome_user_data_dir") or ctx.extra.get("browser_user_data_dir") or ""),
                api_key_timeout=int(ctx.extra.get("api_key_timeout", 45) or 45),
            )

        def _run_worker(worker, ctx, artifacts):
            return worker.run(
                email=ctx.identity.email,
                password=ctx.password or "",
                provider_account_ref=str(ctx.extra.get("provider_account_ref") or ctx.identity.email),
            )

        return BrowserRegistrationAdapter(
            result_mapper=lambda ctx, result: self._map_freemodel_result(result),
            browser_worker_builder=_build_worker,
            browser_register_runner=_run_worker,
            otp_spec=OtpSpec(
                keyword="FreeModel",
                code_pattern=r"\b(\d{6})\b",
                wait_message="等待 FreeModel 邮箱验证码...",
                success_label="FreeModel 验证码",
                timeout=resolve_timeout(self.config.extra or {}, ("otp_timeout",), 180),
            ),
        )

    def check_valid(self, account: Account) -> bool:
        api_key = str(account.token or (account.extra or {}).get("api_key") or "").strip()
        if not api_key:
            return False
        import requests

        try:
            response = requests.get(
                f"{FREEMODEL_API_BASE}/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=15,
            )
            return response.status_code != 401
        except Exception:
            return False

    def get_quota(self, account: Account) -> dict:
        return {
            "provider": self.name,
            "api_base": FREEMODEL_API_BASE,
            "has_api_key": bool(str(account.token or (account.extra or {}).get("api_key") or "").strip()),
            "telegram_status": ((account.extra or {}).get("telegram_binding") or {}).get("status", ""),
        }

