# Phone

Bland calling and texting for this agent, set up with Bland's
[agent onboarding (device-authorization) flow](https://docs.bland.ai/platform/connect-your-agent).

## Usage

```bash
python3 scripts/bland.py status    # key source, auth check, number, A2P link state
python3 scripts/bland.py whoami    # verifies the key with GET /v1/me
python3 scripts/bland.py sms  --to +14155550123 --message "Hello"   # sends, then waits for delivery status
python3 scripts/bland.py sms-status --conversation <id> [--message-id <id>]
python3 scripts/bland.py call --to +14155550123 --task "Introduce yourself and ..."

# First-time setup without a key:
python3 scripts/bland.py start     # prints the approval link and code
python3 scripts/bland.py poll      # polls at the server's interval until approved/expired
```

During approval the owner picks the **Agent Phone Plan** (dedicated number, needed for SMS)
or free credits (no number, no texting).

## Where the key comes from

First match wins:

1. `~/.config/bland/credentials.json`, written by `poll` (override the folder with `BLAND_CONFIG_DIR`).
2. The `BLAND_API_KEY` environment variable.
3. A network secret for `api.bland.ai` saved on the cloud environment. The proxy overwrites the
   `Authorization` header on every request, so the script sends a placeholder and never sees the key.
   This is the durable option for cloud sessions; files in the container vanish when it is reclaimed.

When no number is saved locally, `sms` uses the account's first SMS number from `GET /v1/sms/numbers`.

## Secret handling

- The API key and the onboarding `device_code` are written only to `~/.config/bland/`
  (directory `0700`, files `0600`). Nothing secret is stored in this repo.
- The script never prints either value; all output also passes through a redaction filter.
- The device flow is region-bound: pass `--base-url https://eu.api.bland.ai` (or set `BLAND_BASE_URL`)
  if the dashboard is regional.

## Known issue: SMS error 30034

`POST /v1/sms/send` returning HTTP 200 only means Bland accepted the text. If `sms` reports
`status=undelivered error_code=30034`, the number is not linked to an approved US A2P 10DLC campaign
(`status` shows `A2P messaging_service_sid present: False`). Bland support has to link the number.
