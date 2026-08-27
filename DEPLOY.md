# Deploying SOW Family Contact App (Docker)

Stdlib-only Python server (no gunicorn, no pip deps). `north7.sqlite` is
**mounted at runtime**, not baked into the image — it holds both the member
data and the `settings` table (password hash) written by
`scripts/set_password.py`.

## 1. Set the password (do this on the host, before or after the container is up)

```bash
python3 scripts/set_password.py
```

This writes a salted PBKDF2 hash into `north7.sqlite` directly — the same
file the container mounts, so no rebuild/restart is needed for the container
to pick it up (login checks the DB fresh on every request). The server
refuses to start if no password has ever been set.

## 2. Build + run with docker compose (local port only)

```bash
docker compose up -d --build
```

Publishes `127.0.0.1:8010`, mounts `north7.sqlite` read-write, sets
`restart: unless-stopped`, and inherits the image `HEALTHCHECK` (`/healthz`,
no auth required).

```bash
curl -s localhost:8010/healthz          # {"status":"ok"}
docker compose ps                       # STATUS shows "(healthy)"
```

## 2b. Behind the existing Traefik (no host port)

If the host already runs Traefik, use the `compose.traefik.yml` override
instead of a plain host port — Traefik reaches the app over its shared
network and issues TLS automatically via the `myresolver` Cloudflare
DNS-challenge resolver. Set the network name and router name in that file
to match your own Traefik.

`.env` (not committed to git — the real values live on the host):

```ini
SOW_HOST=your.host.example
SOW_DB_FILE=./north7.sqlite
```

```bash
docker compose -f docker-compose.yml -f compose.traefik.yml up -d --build
```

The override adds a router/service name, the `websecure` entrypoint, the
`myresolver` cert, container port `8000`, and `SOW_ENV=production` — which
is what keeps the page title clean; any instance started without it (plain
`docker compose up`, or `python3 server.py`) titles itself
`dev | 荒野親子團通訊錄`. DNS for `SOW_HOST` must already point at this host.

## 3. Updating

- **Code:** rebuild the image and `docker compose up -d --build` (add
  `-f compose.traefik.yml` if running behind Traefik).
- **Data:** overwrite `north7.sqlite` on the host — no restart needed, the
  server queries it fresh per request.
- **Password:** re-run `python3 scripts/set_password.py` — this also rotates
  the session-signing secret, logging out every previously "remembered"
  device.

## Notes

- Single-process `ThreadingHTTPServer`, fine at this traffic scale (one
  family group). No secrets baked into the image, no external services.
- `north7.sqlite` is mounted read-write (not `:ro`) because the app's own
  password-reset flow writes to it; if you'd rather rotate the password from
  inside the container instead of the host, run
  `docker compose exec -u root app python3 scripts/set_password.py`
  (`make set-password` / `make set-admin-password` do this for you). The
  `-u root` matters: the image runs as uid 10001 while the mounted DB is
  owned by the host user, so without it SQLite reports
  "attempt to write a readonly database".
