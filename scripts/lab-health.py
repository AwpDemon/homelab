#!/usr/bin/env python3
"""
lab-health.py — one-shot homelab health check.

Polls the services I care about, reports status in a table, and exits
non-zero if anything critical is down. Designed to be dumb and fast —
runs from cron, output goes to systemd journal, alert is "if anything
hit CRIT in the last hour, wake me up."

Checks:
  * HTTPS endpoint reachable via the Cloudflare Tunnel
  * Authentik /if/flow/default-authentication-flow/ returns 200
  * cloudflared metrics endpoint exposes a connected tunnel
  * Local LLM's /v1/models endpoint returns at least one model
"""

import argparse
import json
import sys
from urllib import request, error

TIMEOUT = 5
CRIT, WARN, OK = "CRIT", "WARN", "OK "


def check_https(url, expect_status=200):
    try:
        req = request.Request(url, headers={"User-Agent": "lab-health/1.0"})
        with request.urlopen(req, timeout=TIMEOUT) as resp:
            if resp.status == expect_status:
                return OK, f"HTTP {resp.status}"
            return WARN, f"HTTP {resp.status}"
    except error.HTTPError as e:
        return WARN, f"HTTP {e.code}"
    except Exception as e:
        return CRIT, f"{type(e).__name__}: {e}"


def check_cloudflared_metrics(url):
    """cloudflared exposes a Prometheus-format /metrics. Parse the
    connected-tunnels gauge, alert if zero."""
    try:
        with request.urlopen(url, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return CRIT, f"unreachable: {e}"
    for line in body.splitlines():
        if line.startswith("cloudflared_tunnel_ha_connections"):
            try:
                val = int(float(line.split()[-1]))
                return (OK if val > 0 else CRIT), f"{val} tunnel connections"
            except ValueError:
                pass
    return WARN, "metric not found"


def check_llm_models(url):
    """OpenAI-compatible endpoint. If it has at least one model loaded,
    the server is alive and responsive."""
    try:
        with request.urlopen(url, timeout=TIMEOUT) as resp:
            body = json.loads(resp.read())
    except Exception as e:
        return CRIT, f"unreachable: {e}"
    data = body.get("data") or []
    return (OK, f"{len(data)} model(s) loaded") if data else (CRIT, "no models loaded")


CHECKS = [
    ("home.<domain>", check_https, "https://home.example/"),
    ("auth",          check_https, "https://auth.example/if/flow/default-authentication-flow/"),
    ("cloudflared",   check_cloudflared_metrics, "http://127.0.0.1:2000/metrics"),
    ("llm /v1/models", check_llm_models, "http://127.0.0.1:8001/v1/models"),
]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = ap.parse_args(argv)

    results = []
    for name, fn, arg in CHECKS:
        try:
            status, detail = fn(*arg) if isinstance(arg, tuple) else fn(arg)
        except Exception as e:
            status, detail = CRIT, f"exception: {e}"
        results.append({"name": name, "status": status.strip(), "detail": detail})

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"{'service':<20} {'status':<6} detail")
        print("-" * 60)
        for r in results:
            print(f"{r['name']:<20} {r['status']:<6} {r['detail']}")

    # Exit 1 if any CRIT — cron can key off this
    return 1 if any(r["status"] == "CRIT" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
