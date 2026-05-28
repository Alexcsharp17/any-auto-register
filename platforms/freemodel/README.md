# FreeModel HPE Plugin

Browser-assisted FreeModel provisioning for `ai-harness`.

The plugin implements:

- FreeModel account login/registration with mailbox OTP.
- Proton Harness mailbox support through Proton Bridge IMAP.
- Telegram verification through SSPanel and `scripts/provider-bindings`.
- API-key extraction from the FreeModel keys dashboard.

## Runtime Shape

Use the platform with `executor_type=headed` or `executor_type=headless`.

Required resources:

```text
mailbox provider: proton_harness
telegram provider: sspanel_harness
browser: Playwright Chromium or Camoufox when the package is available
state DB: AI_HARNESS_BINDINGS_DB or /var/lib/ai-harness/provider-bindings.sqlite
```

Example `RegisterConfig.extra` keys:

```text
identity_provider=mailbox
mail_provider=proton_harness
proton_env_file=/opt/ai-harness/secrets/proton-mail.env
proton_aliases=wgsr7b2t7@mozmail.com,l081p64su@mozmail.com
telegram_provider=sspanel_harness
sspanel_env_file=/opt/ai-harness/secrets/sspanel.env
bindings_db=/var/lib/ai-harness/provider-bindings.sqlite
provider_bindings_script=/opt/ai-harness/scripts/provider-bindings
browser_engine=auto
browser_user_data_dir=/var/lib/ai-harness/browser/freemodel
```

## Flow

1. Open `https://freemodel.dev/dashboard/keys`.
2. Submit the Mozilla Relay alias.
3. Read the six-digit FreeModel code from Proton Bridge IMAP.
4. Enter the code and wait for the dashboard.
5. Click `Bind Telegram`, extract the `https://t.me/FreeModelDevBot?start=<token>` link.
6. Call SSPanel `/api/v2/telegram/bot-start/test` with `excludeTelegramIds` from `scripts/provider-bindings exclude`.
7. Record the SSPanel response through `scripts/provider-bindings record`.
8. Open the keys dashboard and extract or create an API key.

Secrets, cookies, raw one-time codes, Telegram start links, and API keys must stay outside git.

## Smoke Check

Run this before a live provisioning attempt:

```bash
python scripts/freemodel_smoke.py \
  --env-file /opt/ai-harness/secrets/sspanel.env \
  --config-json '{"proton_aliases":"wgsr7b2t7@mozmail.com","bindings_db":"/var/lib/ai-harness/provider-bindings.sqlite"}'
```

The smoke check validates imports, provider factories, SSPanel configuration
shape, and the provider-bindings SQLite schema. It does not create a FreeModel
account, read Proton mail, call SSPanel, or print secrets.
