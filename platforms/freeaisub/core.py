"""freeaisub (智联 free ai) platform core implementation."""
from __future__ import annotations

import logging
from typing import Callable
from providers.sms.sspanel_harness import SSPanelHarnessTelegramProvider, TelegramBotActivationResult

FREEAISUB_BOT_LINK = "https://t.me/freeaisub_bot"
DEFAULT_REFERRAL_CODE = "e2f59b99d1"

class FreeaisubHarness:
    def __init__(self, sspanel_config: dict, log_fn: Callable = print):
        self.log = log_fn
        self.provider = SSPanelHarnessTelegramProvider.from_config(sspanel_config)

    def register_referral(
        self,
        referral_code: str | None = None,
        provider_account_ref: str = "campaign_owner",
        telegram_id_override: str | None = None,
    ) -> TelegramBotActivationResult:
        code = (referral_code or DEFAULT_REFERRAL_CODE).strip()
        bot_link = f"{FREEAISUB_BOT_LINK}?start={code}"
        self.log(f"Отправка реферального старта в @freeaisub_bot с кодом: {code}")
        
        # Если передан конкретный telegram_id, мы можем переопределить limit или exclude
        # Но по умолчанию sspanel сам выберет свободный аккаунт из пула
        result = self.provider.activate_bot_link(
            bot_link=bot_link,
            provider="freeaisub",
            provider_account_ref=provider_account_ref,
            bot_response_wait_ms=4000,
        )
        self.log(f"Результат старта: status={result.status}, telegram_id={result.telegram_id}")
        return result

    def checkin(
        self,
        telegram_id: str,
        provider_account_ref: str = "daily_checkin",
    ) -> TelegramBotActivationResult:
        self.log(f"Выполнение ежедневного чек-ина для Telegram ID: {telegram_id}")
        
        # Для чек-ина мы шлем команду /checkin (или "🎁 Redeem" / "📊 Progress")
        # Мы используем API sspanel, передавая конкретный telegram_id в exclude (чтобы выбрать его)
        # На самом деле, чтобы заставить SSPanel выполнить команду от конкретного аккаунта,
        # API sspanel должен поддерживать выбор аккаунта. 
        # Если API sspanel выбирает аккаунт на основе exclude, то чтобы выбрать ИМЕННО telegram_id,
        # мы можем временно настроить sspanel_harness или передать параметры.
        # В нашей схеме API:
        # POST /api/v2/telegram/bot-start/test
        # {
        #   "botLink": "https://t.me/freeaisub_bot",
        #   "limit": 1,
        #   "excludeTelegramIds": [...], -- исключить все кроме нужного
        #   "messages": ["/checkin"]
        # }
        #
        # Чтобы выбрать конкретный telegram_id, мы можем передать в excludeTelegramIds ВСЕ аккаунты,
        # КРОМЕ этого telegram_id. 
        # Но проще, если API SSPanel позволяет передать targetTelegramId. 
        # Если нет, sspanel_harness.py использует exclude_ids из БД.
        # Давай вызовем sspanel с messages=["/checkin"]
        
        # Сначала получим список исключений, но уберем оттуда наш telegram_id, чтобы sspanel выбрал именно его
        exclude_ids = self.provider.recorder.exclude_telegram_ids("freeaisub")
        if telegram_id in exclude_ids:
            exclude_ids.remove(telegram_id)
            
        payload = {
            "botLink": FREEAISUB_BOT_LINK,
            "limit": 1,
            "excludeTelegramIds": exclude_ids,
            "messages": ["/checkin"],
            "botResponseWaitMs": 3000,
            "dryRun": False,
        }
        
        # Выполняем запрос напрямую через провайдер
        import requests
        self.log(f"Отправка запроса /checkin в SSPanel для {telegram_id}")
        response = requests.post(
            f"{self.provider.base_url}/api/v2/telegram/bot-start/test",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.provider._token()}",
            },
            json=payload,
            timeout=self.provider.timeout,
        )
        response.raise_for_status()
        raw_response = response.json()
        
        # Записываем результат операции
        record_result = self.provider.recorder.record(
            provider="freeaisub",
            provider_account_ref=provider_account_ref,
            start_link=FREEAISUB_BOT_LINK,
            response=raw_response,
            executor=self.provider.executor,
        )
        
        first = self.provider._first_result(raw_response)
        return TelegramBotActivationResult(
            provider="freeaisub",
            start_link=FREEAISUB_BOT_LINK,
            status=str(record_result.get("status") or self.provider._classify(first)),
            telegram_id=str(first.get("telegramId") or first.get("telegram_id") or telegram_id),
            start_code="/checkin",
            bot_response_status=str(first.get("botResponseStatus") or ""),
            bot_response_text=str(first.get("botResponseText") or ""),
            raw_response=raw_response,
        )
