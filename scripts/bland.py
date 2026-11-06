#!/usr/bin/env python3
"""Bland calling and texting helper for this agent.

Implements the device-authorization flow from
https://docs.bland.ai/platform/connect-your-agent and thin REST wrappers for
SMS and calls. Standard library only.

Secret handling:
  * The API key and the device_code are written only to 0600 files under
    ~/.config/bland/ (override with BLAND_CONFIG_DIR), never to stdout/stderr.
  * Every line this script prints passes through redact(), which replaces any
    known secret with [REDACTED] as a second line of defence.

Commands:
  start  [--client-name NAME] [--base-url URL]  begin onboarding, print link + code
  poll                                         poll at the server's interval until done
  status                                       show saved, non-secret connection info
  whoami                                       verify the saved key against GET /v1/me
  sms    --to +1XXXXXXXXXX --message TEXT [--objective TEXT]
  call   --to +1XXXXXXXXXX --task TEXT
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

DEFAULT_BASE_URL = "https://api.bland.ai"
CONFIG_DIR = os.path.expanduser(os.environ.get("BLAND_CONFIG_DIR", "~/.config/bland"))
CRED_PATH = os.path.join(CONFIG_DIR, "credentials.json")
STATE_PATH = os.path.join(CONFIG_DIR, "onboarding.json")

_SECRETS = set()


def redact(text):
    text = str(text)
    for s in _SECRETS:
        if s:
            text = text.replace(s, "[REDACTED]")
    return text


def out(*parts):
    print(redact(" ".join(str(p) for p in parts)), flush=True)


def write_private(path, obj):
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    os.chmod(CONFIG_DIR, 0o700)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def read_json(path):
    with open(path) as f:
        return json.load(f)


def load_creds():
    if not os.path.exists(CRED_PATH):
        sys.exit(f"No saved Bland credentials at {CRED_PATH}. Run: bland.py start && bland.py poll")
    creds = read_json(CRED_PATH)
    _SECRETS.add(creds.get("api_key"))
    return creds


def request(method, url, body=None, headers=None):
    """Return (http_status, parsed_json_or_text, response_headers)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw, status, hdrs = r.read().decode(), r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        raw, status, hdrs = e.read().decode(errors="replace"), e.code, dict(e.headers or {})
    try:
        return status, json.loads(raw), hdrs
    except ValueError:
        return status, raw, hdrs


def first_error(payload):
    if isinstance(payload, dict) and payload.get("errors"):
        return payload["errors"][0] if isinstance(payload["errors"], list) else payload["errors"]
    return None


# ---------------------------------------------------------------- onboarding

def cmd_start(args):
    base = args.base_url.rstrip("/")
    body = {"client_name": args.client_name}
    status, payload, _ = request("POST", f"{base}/v1/agent/onboarding/start", body)
    if status != 200 or not isinstance(payload, dict) or not payload.get("data"):
        out(f"start failed: HTTP {status}", json.dumps(first_error(payload) or payload)[:500])
        sys.exit(1)
    d = payload["data"]
    _SECRETS.add(d["device_code"])
    write_private(STATE_PATH, {
        "base_url": base,
        "device_code": d["device_code"],
        "interval": d.get("interval", 5),
        "expires_at": time.time() + d.get("expires_in", 900),
        "user_code": d.get("user_code"),
    })
    out("verification_url_complete:", d.get("verification_url_complete"))
    out("verification_url:", d.get("verification_url"))
    out("user_code:", d.get("user_code"))
    out("expires_in_seconds:", d.get("expires_in"))
    out("poll_interval_seconds:", d.get("interval"))


def cmd_poll(_args):
    if not os.path.exists(STATE_PATH):
        sys.exit("No onboarding in progress. Run: bland.py start")
    st = read_json(STATE_PATH)
    _SECRETS.add(st["device_code"])
    base, interval, expires_at = st["base_url"], int(st.get("interval", 5)), st["expires_at"]
    n = 0
    while True:
        if time.time() > expires_at + 5:
            out("result: expired (15-minute window passed without approval). Run start again.")
            sys.exit(2)
        time.sleep(interval)
        n += 1
        status, payload, hdrs = request("POST", f"{base}/v1/agent/onboarding/poll",
                                        {"device_code": st["device_code"]})
        err = first_error(payload)
        if status == 429:
            code = (err or {}).get("error")
            new = (err or {}).get("interval") or hdrs.get("Retry-After") or hdrs.get("retry-after")
            interval = max(interval, int(new)) if new else interval + 5
            out(f"[{time.strftime('%H:%M:%S')}] poll {n}: HTTP 429 {code}; backing off to {interval}s")
            continue
        if status != 200 or not isinstance(payload, dict) or not payload.get("data"):
            out(f"[{time.strftime('%H:%M:%S')}] poll {n}: HTTP {status}", json.dumps(err or payload)[:300])
            if 500 <= status < 600:
                continue
            sys.exit(1)
        d = payload["data"]
        s = d.get("status")
        if s == "pending":
            out(f"[{time.strftime('%H:%M:%S')}] poll {n}: pending")
            continue
        if s == "expired":
            out(f"[{time.strftime('%H:%M:%S')}] poll {n}: expired. Run start again "
                "(also check the dashboard/API region pairing if you had just approved).")
            sys.exit(2)
        if s == "approved":
            key = d.get("api_key")
            _SECRETS.add(key)
            if not key:
                out("approved but no api_key in response; nothing saved")
                sys.exit(1)
            plan = d.get("plan") or {}
            write_private(CRED_PATH, {
                "api_key": key,
                "base_url": base,
                "org_id": d.get("org_id"),
                "phone_number": d.get("phone_number"),
                "plan": plan,
                "client_name": d.get("client_name"),
                "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            os.remove(STATE_PATH)
            out(f"[{time.strftime('%H:%M:%S')}] poll {n}: approved")
            out("api_key: saved to", CRED_PATH, "(mode 600, not printed)")
            out("phone_number:", d.get("phone_number"))
            out("plan:", plan.get("display_name"), "| plan status:", plan.get("status"),
                "| allowed countries:", plan.get("allowed_countries"))
            return
        out(f"[{time.strftime('%H:%M:%S')}] poll {n}: unexpected status {s!r}")
        sys.exit(1)


# ---------------------------------------------------------------- usage

def cmd_status(_args):
    c = load_creds()
    plan = c.get("plan") or {}
    out("credentials file:", CRED_PATH, oct(os.stat(CRED_PATH).st_mode & 0o777))
    out("api_key present:", bool(c.get("api_key")))
    out("base_url:", c.get("base_url"))
    out("phone_number:", c.get("phone_number"))
    out("plan:", plan.get("display_name"), "| status:", plan.get("status"))


def cmd_whoami(_args):
    c = load_creds()
    status, payload, _ = request("GET", f"{c['base_url']}/v1/me", headers={"authorization": c["api_key"]})
    out("GET /v1/me -> HTTP", status)
    if isinstance(payload, dict):
        out("account status:", payload.get("status"))
        out("response fields:", sorted(payload.keys()))
    else:
        out(str(payload)[:300])
    sys.exit(0 if status == 200 else 1)


def cmd_sms(args):
    c = load_creds()
    if not c.get("phone_number"):
        sys.exit("No dedicated number saved. Texting requires the Agent Phone Plan.")
    body = {"user_number": args.to, "agent_number": c["phone_number"], "agent_message": args.message}
    if args.objective:
        body["objective"] = args.objective
    status, payload, _ = request("POST", f"{c['base_url']}/v1/sms/send", body,
                                 headers={"authorization": c["api_key"],
                                          "idempotency-key": args.idempotency_key or str(uuid.uuid4())})
    out("POST /v1/sms/send -> HTTP", status)
    out(json.dumps(payload)[:800])
    sys.exit(0 if status == 200 and not first_error(payload) else 1)


def cmd_call(args):
    c = load_creds()
    body = {"phone_number": args.to, "task": args.task}
    status, payload, _ = request("POST", f"{c['base_url']}/v1/calls", body,
                                 headers={"authorization": c["api_key"]})
    out("POST /v1/calls -> HTTP", status)
    out(json.dumps(payload)[:800])
    sys.exit(0 if status == 200 and not first_error(payload) else 1)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--client-name", default="claude-code-phone-agent")
    s.add_argument("--base-url", default=DEFAULT_BASE_URL,
                   help="Must match the owner's dashboard region (e.g. https://eu.api.bland.ai)")
    s.set_defaults(fn=cmd_start)
    sub.add_parser("poll").set_defaults(fn=cmd_poll)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("whoami").set_defaults(fn=cmd_whoami)
    m = sub.add_parser("sms")
    m.add_argument("--to", required=True)
    m.add_argument("--message", required=True)
    m.add_argument("--objective")
    m.add_argument("--idempotency-key")
    m.set_defaults(fn=cmd_sms)
    k = sub.add_parser("call")
    k.add_argument("--to", required=True)
    k.add_argument("--task", required=True)
    k.set_defaults(fn=cmd_call)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
