# homelab

[![lint](https://github.com/AwpDemon/homelab/actions/workflows/lint.yml/badge.svg)](https://github.com/AwpDemon/homelab/actions/workflows/lint.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Highlights**
- Public-facing services behind a **Cloudflare Tunnel** — zero inbound ports open on my router, real IP never leaves the LAN.
- **Authentik IdP** centralizes auth for ~10 self-hosted apps; one place for MFA, session revocation, OIDC + forward-auth for the ones that don't speak OIDC.
- **OpenAI-compatible local LLM endpoint** so any tool that expects ChatGPT/Claude can point at `localhost` with zero glue code.
- One-shot health check script (`scripts/lab-health.py`, stdlib only) that checks the tunnel, the SSO login flow and the LLM endpoint, with JSON output.

Notes from running a public-facing homelab. Not a runbook: the real configs, hostnames and IPs stay private. This is the stuff I figured out the hard way and would want to remember if I were setting up from scratch.

## What this is

A handful of self-hosted services (media, monitoring, a few internal web apps, a local LLM stack) running on commodity hardware. Public entry points sit behind Cloudflare. Anything sensitive sits behind SSO.

## Topology

```mermaid
flowchart LR
    subgraph Internet["Public internet"]
        USER[Browser / client]
    end

    subgraph CF["Cloudflare edge"]
        PROXY[HTTP proxy + WAF + DDoS]
        DNS[DNS for the lab's domain]
    end

    subgraph Lab["Private LAN"]
        direction TB
        TUNNEL[cloudflared tunnel<br/>outbound-only]
        AUTH[Authentik IdP + outposts]

        subgraph Apps["Protected apps"]
            MEDIA[Media stack]
            MONITOR[Grafana / Prometheus]
            INTERNAL[Internal web apps]
            LLM[Local LLM<br/>OpenAI-compatible]
        end
    end

    USER -->|HTTPS| PROXY
    PROXY -->|outbound-only tunnel| TUNNEL
    TUNNEL --> AUTH
    AUTH -->|OIDC / forward-auth| Apps
    USER -.-> DNS
    DNS -.-> PROXY

    classDef edge fill:#f2c811,stroke:#b08400,color:#333
    classDef private fill:#d6eaf8,stroke:#2874a6,color:#1b4f72
    class CF edge
    class Lab,Apps private
```

No inbound ports from the public internet. Everything comes in through the Cloudflare HTTP proxy and reaches the LAN through the outbound-only `cloudflared` tunnel.

## The problems I had to solve

### 1. Getting services reachable from the internet without exposing my home IP

My ISP hands out dynamic IPs, CGNAT is a thing, and port-forwarding the router is both a security smell and a ticket to every opportunistic scanner on the internet. The answer is a Cloudflare Tunnel — `cloudflared` runs on the lab, makes an outbound connection to Cloudflare, and Cloudflare proxies incoming traffic back through the tunnel.

What this actually buys:
- No inbound ports open on my router, ever. Nothing to find with `nmap`.
- My real IP never touches client connections — Cloudflare sees it, clients see a Cloudflare IP.
- DDoS scrubbing happens at Cloudflare's edge before anything hits my box.
- Cert management is handled by Cloudflare (origin cert + proxy). No Let's Encrypt renewal cron to babysit.

Trade-off: HTTP/HTTPS only on the free tier. For non-HTTP protocols (SSH, game servers) you either pay for Spectrum, use a protocol-specific proxy, or keep them on a private network such as a VPN.

### 2. Authenticating self-hosted apps without building a login for each one

Most self-hosted software ships with either no auth or a cursed built-in login page. Running ten of these with ten separate passwords is how you end up with one reused password everywhere.

Solved with **Authentik** as a central IdP. Every protected service sits behind an Authentik outpost — the outpost is a reverse proxy that enforces auth before the request ever reaches the app. OIDC for anything that speaks it, forward-auth for anything that doesn't. One login, one place to revoke a session, one place to enforce 2FA.

Setup gotcha: the outpost needs to be on the same domain (or a subdomain with proper cookie scoping) as the service it guards, otherwise the cookie won't propagate. Took me a few hours of 403s to figure that out.

### 3. Running inference locally instead of paying per-token

For small automation (summarize a doc, draft a shell command, throw ideas at something), the round-trip to a paid API is both slow and expensive if I'm iterating. Local models on a GPU I already owned are fine for these.

Stack is intentionally boring: a small serving layer (chose something that exposes an OpenAI-compatible API so tools that expect ChatGPT or Claude can point at `localhost` without rewriting), a couple of model weights sized for my VRAM, and a tmux session that stays up. Nothing clever, but the OpenAI-compatible endpoint is the unlock — it means a dozen CLI tools "just work" without any custom glue.

Trade-off I hadn't appreciated: context window costs VRAM *nonlinearly*. Doubling context can quarter your usable batch size. For short-turn tasks this is fine; for long-doc work you're going back to a paid model anyway.

## Sanitized configs

A few reference configs in `configs/` that show the shape without exposing credentials or internal IPs. They're commit-safe — all secrets, tunnel UUIDs, and IPs are placeholders. The actual values live in a `.env` file that never leaves the host.

- [`configs/cloudflared-sanitized.yml`](configs/cloudflared-sanitized.yml) — tunnel ingress rules with timeouts and the `/metrics` endpoint exposed to Prometheus
- [`configs/authentik-proxy-outpost.yml`](configs/authentik-proxy-outpost.yml) — docker-compose for the forward-auth outpost + Caddyfile snippet showing the forward-auth dance
- [`configs/prometheus-scrape.yml`](configs/prometheus-scrape.yml) — scrape targets for node exporters, Caddy, Authentik, cloudflared, and the NVIDIA GPU exporter

## Health check script

`scripts/lab-health.py` is a one-shot health poller — what I run from cron to get an alert if anything important is down. Checks:

- HTTP reachability through the Cloudflare tunnel
- Authentik's login flow endpoint returns 200
- `cloudflared` `/metrics` reports >0 connected tunnel connections
- Local LLM's OpenAI-compatible `/v1/models` has at least one model loaded

Exits nonzero if any check is CRIT, so cron's mail-on-failure does the alerting. `--json` emits machine-readable output for Prometheus `textfile` collection. Written in stdlib only — no pip install, runs on any Python 3.8+ host.

## What I took away

Most of the "homelab is hard" stuff is actually operations-in-miniature — the same problems a startup SRE deals with, just without the pager. DNS, TLS, SSO, reverse proxies, rate limits, capacity planning, observability. I didn't set out to learn any of this, I set out to host a media server and it got out of hand.
