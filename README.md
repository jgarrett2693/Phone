# Phone

Bland calling and texting for this agent, set up with Bland's
[agent onboarding (device-authorization) flow](https://docs.bland.ai/platform/connect-your-agent).

## Usage

```bash
python3 scripts/bland.py start     # prints the approval link and code
python3 scripts/bland.py poll      # polls at the server's interval until approved/expired
python3 scripts/bland.py status    # saved number and plan (no secrets)
python3 scripts/bland.py whoami    # verifies the saved key with GET /v1/me
python3 scripts/bland.py sms  --to +14155550123 --message "Hello"
python3 scripts/bland.py call --to +14155550123 --task "Introduce yourself and ..."
```

During approval the owner picks the **Agent Phone Plan** (dedicated number, needed for SMS)
or free credits (no number, no texting).

## Secret handling

- The API key and the onboarding `device_code` are written only to `~/.config/bland/`
  (directory `0700`, files `0600`; override with `BLAND_CONFIG_DIR`). Nothing secret is stored in this repo.
- The script never prints either value; all output also passes through a redaction filter.
- Cloud containers are ephemeral: the saved key is lost when the container is reclaimed.
  For a durable setup, store a key as an environment network secret for `api.bland.ai`
  rather than in a file.
- The device flow is region-bound: pass `--base-url https://eu.api.bland.ai` (etc.) if the
  dashboard is regional.
