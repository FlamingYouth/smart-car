# Developer notes: Tesla WeChat / Telegram notifier

Read README.md for configuration, sample sends, and deployment. Python 3.9+.

## Modules

- main.py: YAML/environment configuration, logging, lifecycle, health marker, component-only CLI tests.
- wechat_client.py: group robot transport, strict URL validation, per-type/per-car cooldown and deduplication, rolling per-process quota.
- notification_client.py: independent YAML/environment channel switches and failure-isolated fan-out.
- telegram_client.py: official Bot API text transport, explicit per-channel proxy and safe error logging.
- mqtt_listener.py: TeslaMate MQTT event processing and original live notification templates.
- task_scheduler.py: original trip/report templates and scheduler.
- database_manager.py: existing read-only PostgreSQL queries and summary dataclasses.
- scripts/send_notification_samples.py: offline in-memory synthetic cases; no real DB, MQTT, or vehicle connection.

The notification templates in mqtt_listener.py, task_scheduler.py, and main.py lifecycle messages
must not be changed unless explicitly requested. Do not revive disabled wake/sleep/door notifications
as part of a transport change. Do not claim charging-start notifications or unused report metrics work.

## Credentials

WeChat uses WECHAT_WEBHOOK_URL or wechat.webhook_url, without app credentials,
application-token API, notification proxy or default mentions.
Telegram uses telegram.enabled/bot_token/chat_id/proxy or their TELEGRAM_* environment
overrides. Its proxy applies only to Telegram; use the official API endpoint.
Missing channel switches retain legacy defaults: WeChat true, Telegram false.
Tokens and recipient IDs must stay in ignored private configuration, never public examples.
config.yaml is a public example. Real .env*, config-prod.yaml, .private/ and private-backups/ are ignored
by Git and Docker. Never log or embed real Webhook keys or database passwords.
Existing Git history may contain legacy secrets; ignoring or sanitizing the current working copy
does not remove old commits. Do not rewrite history or push without explicit authorization.

The client's HTTP session has trust_env=False and redirects disabled. Failure logs intentionally
omit exception text and API errmsg because either could expose secrets.
Treat only HTTP 200 and integer errcode=0 as success. No automatic transport retries.
Skipped disabled/cooldown/duplicate calls retain legacy True semantics; not actual delivery.
Each client allows 18 attempted robot requests per rolling minute, including failures and chunks.
This quota is per process, not distributed. No automatic queuing/backfill.

Version 4.1 adapts the legacy textcard interface to ordinary robot text, like all other notifications.
Preserve the original title and body, append the validated detail URL as "查看详情：URL".
Never use Markdown link syntax or Markdown payloads for these reports. Use the 2048-byte text limit.
Do not promise an identical application-card appearance or a client display not actually observed.

## Verification

Never run production main or compose up as a notification test: they access configured real services.
Use tests/run_offline.py for offline pytest, and tests/Dockerfile for the test image based on the
same final runtime image. Docker tests should have --network none, read-only tests mount,
PYTHONDONTWRITEBYTECODE=1 and PYTEST_DISABLE_PLUGIN_AUTOLOAD=1.
The CLI --test-wechat / --test-telegram / --test-notifications only sends notifications,
without initializing DB/MQTT. Disabled channels are never enabled by a test flag.
The sample tool defaults to preview; --send is explicit and sends 16 synthetic cases plus an intro.
Real sample sends require user authorization and the specified robot only.
Do not print credentials in commands, terminal output or test reports.
Keep isolated test containers separate from existing TeslaMate/Aliyun containers.

## Docker

Dockerfile copies only Python runtime files, sanitized config.yaml, scripts and pinned requirements.lock.
The base image digest and complete runtime dependencies are fixed to the tested versions.
Runtime user is UID 1000. Read-only production config mounts must be readable by that user.
The original local test alias is codex-smart-car-webhook:3.1.0.
Root Compose and server-deploy/docker-compose.yml use the Aliyun notifier image tag 5.0.
Only the notifier image tag changes; do not upgrade unrelated TeslaMate services.
NOMINATIM_PROXY there belongs to TeslaMate geocoding and is not the notification proxy.

## Scope

The notifier has no web UI or vehicle-control operations. This transport migration does not fix
existing unrelated database calculations, charging completion timing races, or other upstream services.
Unit/in-memory tests are not evidence of a live TeslaMate database or vehicle integration.
