# homelab

Notes from running a public-facing homelab out of my apartment. Not a runbook — I keep the actual configs and IPs private. This is the stuff I figured out the hard way and would want to remember if I were setting up from scratch.

## What this is

A handful of self-hosted services (media, monitoring, a few internal web apps, a local LLM stack, a public Minecraft server) running on commodity hardware at my place. Domain is `awpdemon.com`. Public entry points sit behind Cloudflare. Anything sensitive sits behind SSO.

## The problems I had to solve

### 1. Getting services reachable from the internet without exposing my home IP

My ISP hands out dynamic IPs, CGNAT is a thing, and port-forwarding the router is both a security smell and a ticket to every opportunistic scanner on the internet. The answer is a Cloudflare Tunnel — `cloudflared` runs on the lab, makes an outbound connection to Cloudflare, and Cloudflare proxies incoming traffic back through the tunnel.

What this actually buys:
- No inbound ports open on my router, ever. Nothing to find with `nmap`.
- My real IP never touches client connections — Cloudflare sees it, clients see a Cloudflare IP.
- DDoS scrubbing happens at Cloudflare's edge before anything hits my box.
- Cert management is handled by Cloudflare (origin cert + proxy). No Let's Encrypt renewal cron to babysit.

Trade-off: HTTP/HTTPS only on the free tier. For non-HTTP protocols (Minecraft, SSH), you either pay for Spectrum or use a protocol-specific proxy (see below).

### 2. Authenticating self-hosted apps without building a login for each one

Most self-hosted software ships with either no auth or a cursed built-in login page. Running ten of these with ten separate passwords is how you end up with one reused password everywhere.

Solved with **Authentik** as a central IdP. Every protected service sits behind an Authentik outpost — the outpost is a reverse proxy that enforces auth before the request ever reaches the app. OIDC for anything that speaks it, forward-auth for anything that doesn't. One login, one place to revoke a session, one place to enforce 2FA.

Setup gotcha: the outpost needs to be on the same domain (or a subdomain with proper cookie scoping) as the service it guards, otherwise the cookie won't propagate. Took me a few hours of 403s to figure that out.

### 3. Keeping a public Minecraft server online during L7 attacks

Minecraft is TCP 25565. The protocol is chatty, the clients are everywhere, and anyone with a grudge and a booter can make a small server unreachable. Mine got hit.

What worked:
- Put a protocol-aware proxy in front of the server instead of exposing the backend directly. A reverse proxy that understands the Minecraft handshake can drop malformed packets, rate-limit by IP, and absorb connection floods before the backend even sees them.
- Whitelist the backend's firewall to only accept connections from the proxy's IPs. If someone figures out the backend IP directly, they hit a closed port.
- Kick the bot-joiner pattern: too many new unauthenticated handshakes from the same /24 in a short window → temp block. Real players don't do that.
- On the server itself, tune `max-tick-time`, `network-compression-threshold`, and view distance so a single bad tick doesn't snowball. Modded servers with unoptimized plugins are where this bites hardest.

What didn't work: relying on Minecraft's built-in `whitelist` — it kicks you *after* the handshake completes, so you've already spent CPU on the attacker.

### 4. Running inference locally instead of paying per-token

For small automation (summarize a doc, draft a shell command, throw ideas at something), the round-trip to a paid API is both slow and expensive if I'm iterating. Local models on a GPU I already owned are fine for these.

Stack is intentionally boring: a small serving layer (chose something that exposes an OpenAI-compatible API so tools that expect ChatGPT or Claude can point at `localhost` without rewriting), a couple of model weights sized for my VRAM, and a tmux session that stays up. Nothing clever, but the OpenAI-compatible endpoint is the unlock — it means a dozen CLI tools "just work" without any custom glue.

Trade-off I hadn't appreciated: context window costs VRAM *nonlinearly*. Doubling context can quarter your usable batch size. For short-turn tasks this is fine; for long-doc work you're going back to a paid model anyway.

## What I took away

Most of the "homelab is hard" stuff is actually operations-in-miniature — the same problems a startup SRE deals with, just without the pager. DNS, TLS, SSO, reverse proxies, rate limits, capacity planning, observability. I didn't set out to learn any of this, I set out to host a media server and it got out of hand.
