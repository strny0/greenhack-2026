# Demo deploy — basta.one → pc-praha over ZeroTier

```
internet ──▶ basta.one (85.163.109.34, public, nginx)
                 │  ZeroTier
                 ▼
            pc-praha (no public IP)  ──  uvicorn :8099
                                          serves /api/*  +  built frontend
```

One uvicorn process on **pc-praha** serves both the API and the static
frontend (FastAPI mounts `frontend/dist` at `/`). **basta.one** is just a
reverse proxy. DNS is unchanged — `basta.one` already points at the public box.

## 1. pc-praha — get the app there

```bash
# clone (or rsync) the repo, then:
cd gh2026-slop/backend
python3.12 -m venv .venv
./.venv/bin/pip install -r requirements.txt

# build the frontend bundle (or scp the existing frontend/dist over)
cd ../frontend && npm ci && npm run build
```

Copy the LLM secrets — `backend/.env` is git-ignored, so move it manually:

```bash
scp gh2026-slop/backend/.env pc-praha:.../gh2026-slop/backend/.env
# must contain AI_API_KEY (+ optional AI_BASE_URL / AI_MODEL)
```

## 2. pc-praha — run it, bound to all interfaces (so ZeroTier can reach it)

```bash
cd gh2026-slop/backend
PORT=8099 ./.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8099
# (run.sh defaults to 127.0.0.1 — override host to 0.0.0.0 for remote access)
```

Find pc-praha's ZeroTier IP for the proxy config:

```bash
ip -4 addr show | grep -A2 '^.*zt' | grep inet     # e.g. 10.147.19.xx
```

Optional, keep it alive after logout: `tmux new -s grid` then run, or make a
systemd unit (see bottom).

## 3. basta.one — reverse proxy

```bash
sudo apt install -y nginx          # if not already
sudo cp basta-one.nginx.conf /etc/nginx/sites-available/grid-pulse
sudo sed -i 's/PRAHA_ZT_IP/10.147.19.xx/' /etc/nginx/sites-available/grid-pulse
sudo ln -s /etc/nginx/sites-available/grid-pulse /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Visit **http://basta.one**. For TLS: `sudo certbot --nginx -d basta.one`.

## Rehost after a `git pull` (fast loop)

`frontend/dist` is gitignored, so rebuild it on pull, then restart uvicorn:

```bash
cd ~/gh2026-slop
git pull
( cd frontend && npm ci && npm run build )          # rebuild the bundle
( cd backend && ./.venv/bin/pip install -r requirements.txt )   # only if deps changed
# restart the process (tmux/systemd); e.g. with systemd:
sudo systemctl restart grid-pulse
```

## Sanity checks

```bash
# from basta.one, confirm ZeroTier reaches pc-praha:
curl -s http://10.147.19.xx:8099/api/health
# from anywhere:
curl -s http://basta.one/api/health
```

## Optional: systemd unit on pc-praha

```ini
# /etc/systemd/system/grid-pulse.service
[Unit]
Description=Grid Pulse backend
After=network-online.target zerotier-one.service

[Service]
WorkingDirectory=/home/YOU/gh2026-slop/backend
ExecStart=/home/YOU/gh2026-slop/backend/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8099
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now grid-pulse
```
