# Deploying the capture bot 24/7 on the Linux home server

This runs the Telegram capture bot as an always-on Docker container on the home
server (i5 7th-gen, 8GB RAM, no GPU). Captures land in the **Syncthing-synced Hub
vault** so they reach the laptop and phone automatically.

> **Capture surface is Telegram only.** Send links / thoughts / photos / documents to
> the bot from Telegram on your phone — same one-message gesture you used on WhatsApp.
> `batch_ingest.py` stays available for a one-off WhatsApp-export import, but it is not
> part of the live system.

---

## Prerequisites (once, on the server over SSH)

1. **Docker + Compose plugin**
   ```bash
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker "$USER"      # then log out/in so `docker` works without sudo
   docker compose version               # confirm the v2 plugin is present
   ```

2. **Syncthing** — install, pair with your laptop/phone, and share **The Hub** so it
   syncs down to a known path (e.g. `/home/nour/TheHub`).
   ```bash
   sudo apt install syncthing
   systemctl --user enable --now syncthing   # runs Syncthing as your user, on boot
   # Then in the Syncthing web UI (http://localhost:8384) add this device to the
   # existing Hub folder share and let it sync.
   ls /home/nour/TheHub                       # must show: raw/  system/  wiki/  ...
   ```
   The bot only ever reaches your phone because The Hub is Syncthing-synced — this step
   is what makes the whole thing work.

3. **The capture-agent repo** on the server:
   ```bash
   git clone <repo-url> ~/capture-agent   # or copy it over
   cd ~/capture-agent
   ```

---

## Configure (in `~/capture-agent`)

1. **`.env`** — create it out-of-band (never commit it). Minimum:
   ```
   TELEGRAM_BOT_TOKEN=<the real BotFather token>
   TELEGRAM_ALLOWED_USER_ID=6605022627
   VAULT_PATH=/home/nour/TheHub          # the Syncthing Hub path from step 2
   PUID=1000                             # output of `id -u`
   PGID=1000                             # output of `id -g`
   GALLERY_DL_COOKIES_FILE=/secrets/cookies.txt
   ```
   Confirm your ids: `id -u` and `id -g`. If they aren't 1000, set PUID/PGID to match —
   this is what keeps vault files owned by you (not root) so Syncthing/Obsidian stay happy.

2. **Writable cache + cookies file** (must exist before first `up`, or Docker will
   create root-owned dirs in their place):
   ```bash
   mkdir -p data/hf-cache
   touch secrets/cookies.txt             # replace with a real export for IG/FB (below)
   chown -R "$(id -u):$(id -g)" data secrets
   ```

3. **IG/FB cookies** — export a Netscape `cookies.txt` from a logged-in Instagram/Facebook
   session and save it to `secrets/cookies.txt`. An empty file is fine for a first
   YouTube/thought/photo test; Instagram and Facebook links need real cookies. Re-export
   ~every 90 days when the session expires.

---

## Launch

```bash
docker compose up -d --build
docker compose logs -f          # watch for: "Bot starting (polling)…"
```

First run downloads the faster-whisper `small` model (~0.5GB) into `data/hf-cache`;
it's cached after that. `restart: unless-stopped` keeps the bot alive across crashes
and reboots.

**Then decommission the laptop bot:** stop `run_bot.bat` on the Windows laptop and don't
run it again. Only one instance may poll a bot token — running both gives Telegram
`409 Conflict` and drops updates.

---

## Verify (end-to-end)

1. `docker compose ps` → the service is `Up`.
2. `docker compose logs -f` shows `Bot starting (polling)…` with **no** token/whitelist
   exit and **no** `409 Conflict` (409 means something else is still polling the token).
3. From Telegram on your phone, send the bot:
   - a **YouTube or Instagram link** → a new `raw/<slug>-<id>.md` appears with a transcript,
     and a `… VIDEO [[…]] · [source](…) · #unsorted` line in `system/inbox.md`;
   - a **plain thought** → a `… THOUGHT: "…" · #unsorted` line;
   - a **photo** → a file in `raw/assets/` + a `… FILE [[…]] · #unsorted` line.
4. Confirm those files **sync to the laptop/phone** via Syncthing, and that they're
   **owned by you, not root** (`ls -l ~/TheHub/raw | tail`). This is the real proof the
   mount + PUID/PGID are correct.
5. **Reboot the server** → `docker compose ps` shows the bot back `Up` on its own.

---

## Day-to-day

- **Update the bot:** `git pull && docker compose up -d --build`.
- **Logs:** `docker compose logs -f` (or `--tail=100`).
- **Stop / start:** `docker compose down` / `docker compose up -d`.
- **Model/cookies/temp** live outside the vault (`data/hf-cache`, `secrets/`, in-container
  `temp/`), so they never sync to your phone.
- **Known gaps (deferred):** Instagram `/p/` and Facebook `/share/` posts still fail
  capture (two open gallery-dl bugs) and accumulate in `system/skipped.md`. Keep the
  120–180s Instagram spacing if you ever run a bulk `batch_ingest.py` (a real IG soft-block
  happened once) — the live bot is human-paced so it's not at risk.
- **Avoid** firing a bulk `batch_ingest.py` at the exact time Claude is mid-sort on the
  laptop: both write `inbox.md`, and a collision makes a recoverable `.sync-conflict` file.
