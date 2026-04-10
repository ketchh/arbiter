# Arbiter Deployment Guide

This guide covers deploying the Arbiter memory broker in production environments using Docker, systemd, or PM2.

---

## Table of Contents

1. [Environment Variable Reference](#environment-variable-reference)
2. [Docker Deployment](#docker-deployment)
3. [Systemd Service (Linux VPS)](#systemd-service-linux-vps)
4. [PM2 (Node.js Process Manager)](#pm2-nodejs-process-manager)
5. [Reverse Proxy (Nginx)](#reverse-proxy-nginx)
6. [Security Checklist](#security-checklist)

---

## Environment Variable Reference

All environment variables the broker supports. None are required for local development; production deployments should set at least `BROKER_API_KEY` and `BROKER_CORS_ORIGIN`.

### Server and Security

| Variable | Default | Description |
|----------|---------|-------------|
| `BROKER_API_KEY` | _(empty, no auth)_ | Bearer token for API authentication. When set, all endpoints except `GET /health` require `Authorization: Bearer <key>`. |
| `BROKER_BIND_HOST` | `127.0.0.1` | IP address the HTTP server binds to. Use `0.0.0.0` to accept connections from all interfaces (required inside Docker). |
| `BROKER_BIND_PORT` | `8081` | TCP port the HTTP server listens on. |
| `BROKER_RATE_LIMIT` | `60` | Maximum requests per IP per rate window. Set to `0` to disable rate limiting. |
| `BROKER_RATE_WINDOW` | `60` | Rate limit window in seconds. |
| `BROKER_MAX_BODY_SIZE` | `1048576` | Maximum request body size in bytes (default 1 MB). Returns HTTP 413 if exceeded. |
| `BROKER_CORS_ORIGIN` | `*` | Value of the `Access-Control-Allow-Origin` header. Set to a specific domain in production (e.g., `https://app.example.com`). |

### Broker Identity and Routing

| Variable | Default | Description |
|----------|---------|-------------|
| `BROKER_PROJECT_ID` | `sir` | Project identifier used for scoping memory records. Overrides `projectId` in JSON config. |
| `BROKER_USER_ID` | `default-user` | User identifier attached to all memory records. Overrides `userId` in JSON config. |
| `BROKER_WORKSPACE_ID` | _(same as project_id)_ | Workspace identifier for multi-workspace isolation. Overrides `workspaceId` in JSON config. |
| `BROKER_CONFIG_PATH` | `broker/config.json` | Path to the broker JSON config file. Falls back to `broker/config.example.json` if the file does not exist. |
| `BROKER_LOCAL_CACHE_PATH` | `./.broker/cache` | Directory for the flat-file JSON cache backend. |
| `BROKER_CANONICAL_MEMORY` | `supermemory` | Name of the canonical (authoritative) memory backend. |
| `BROKER_CLIENT_ADAPTER` | `claude-code` | Default client name used when normalizing events that do not specify a client. |

### Backend: Supermemory

| Variable | Default | Description |
|----------|---------|-------------|
| `SUPERMEMORY_API_KEY` | _(empty)_ | Supermemory API key. When empty, the adapter operates as a no-op (graceful degradation). |
| `SUPERMEMORY_BASE_URL` | `https://api.supermemory.ai` | Base URL for the Supermemory REST API. Override for self-hosted or staging instances. |

### Backend: Ruflo sqlite

| Variable | Default | Description |
|----------|---------|-------------|
| `RUFLO_DB_PATH` | `.swarm/memory.db` | Path to the Ruflo sqlite database file. |

---

## Docker Deployment

### Build the image

```bash
docker build -t arbiter .
```

The Dockerfile uses `python:3.12-slim`, copies only the package files, and installs via pip. The resulting image has no external dependencies beyond the Python standard library.

### Run the container

```bash
docker run -d \
  --name arbiter \
  -p 8081:8081 \
  -e BROKER_API_KEY=your-secret-key-here \
  -e BROKER_CORS_ORIGIN=https://app.example.com \
  -e SUPERMEMORY_API_KEY=sm-key-here \
  -v arbiter-cache:/app/.broker/cache \
  -v arbiter-swarm:/app/.swarm \
  --restart unless-stopped \
  arbiter
```

The Dockerfile already sets `BROKER_BIND_HOST=0.0.0.0` and `BROKER_BIND_PORT=8081` as defaults, so you do not need to pass them unless you want different values.

### Using an env file

Create a `.env` file (never commit this) and pass it to Docker:

```bash
docker run -d \
  --name arbiter \
  -p 8081:8081 \
  --env-file .env \
  -v arbiter-cache:/app/.broker/cache \
  -v arbiter-swarm:/app/.swarm \
  --restart unless-stopped \
  arbiter
```

### Docker Compose

The following `docker-compose.yml` can be used as a starting point. It is included here as reference; do not create a separate file unless needed.

```yaml
version: "3.8"

services:
  arbiter:
    build: .
    image: arbiter:latest
    container_name: arbiter
    restart: unless-stopped
    ports:
      - "8081:8081"
    env_file:
      - .env
    environment:
      # These override anything in .env if needed
      BROKER_BIND_HOST: "0.0.0.0"
      BROKER_BIND_PORT: "8081"
    volumes:
      # Persist local cache across restarts
      - arbiter-cache:/app/.broker/cache
      # Persist Ruflo sqlite database
      - arbiter-swarm:/app/.swarm
      # Optional: mount a custom config file
      # - ./broker/config.json:/app/broker/config.json:ro
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/health', timeout=3)"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

volumes:
  arbiter-cache:
  arbiter-swarm:
```

Start with:

```bash
docker compose up -d
```

### Volume mounts explained

| Volume | Container path | Purpose |
|--------|----------------|---------|
| `arbiter-cache` | `/app/.broker/cache` | Local JSON cache files (one per scope). Without this mount, cache is lost on container restart. |
| `arbiter-swarm` | `/app/.swarm` | Ruflo sqlite database (`memory.db`). Without this mount, local working memory is lost on restart. |

### Verify the deployment

```bash
# Health check (no auth required)
curl http://localhost:8081/health

# Expected response:
# {"status": "ok", "project_id": "sir", "backends": ["local_cache", "supermemory", "ruflo"]}

# Metrics (requires auth if BROKER_API_KEY is set)
curl -H "Authorization: Bearer your-secret-key-here" http://localhost:8081/metrics
```

### View logs

```bash
docker logs -f arbiter
```

---

## Systemd Service (Linux VPS)

For non-Docker Linux deployments, run Arbiter as a systemd service.

### Prerequisites

```bash
# Install Python 3.11+ if not already present
sudo apt update && sudo apt install -y python3 python3-pip python3-venv

# Create a dedicated user
sudo useradd --system --create-home --shell /usr/sbin/nologin arbiter

# Clone and install
sudo -u arbiter git clone https://github.com/ketchh/arbiter.git /home/arbiter/app
cd /home/arbiter/app
sudo -u arbiter python3 -m venv /home/arbiter/venv
sudo -u arbiter /home/arbiter/venv/bin/pip install .
```

### Environment file

Create `/home/arbiter/.env` with restricted permissions:

```bash
sudo -u arbiter tee /home/arbiter/.env > /dev/null << 'EOF'
BROKER_API_KEY=your-secret-key-here
BROKER_BIND_HOST=127.0.0.1
BROKER_BIND_PORT=8081
BROKER_CORS_ORIGIN=https://app.example.com
BROKER_RATE_LIMIT=120
BROKER_RATE_WINDOW=60
BROKER_MAX_BODY_SIZE=1048576
BROKER_PROJECT_ID=sir
BROKER_USER_ID=default-user
BROKER_LOCAL_CACHE_PATH=/home/arbiter/data/cache
RUFLO_DB_PATH=/home/arbiter/data/memory.db
SUPERMEMORY_API_KEY=sm-key-here
EOF

sudo chmod 600 /home/arbiter/.env
sudo chown arbiter:arbiter /home/arbiter/.env

# Create data directory
sudo -u arbiter mkdir -p /home/arbiter/data
```

### Unit file

Create `/etc/systemd/system/arbiter.service`:

```ini
[Unit]
Description=Arbiter Memory Broker
Documentation=https://github.com/ketchh/arbiter
After=network.target

[Service]
Type=simple
User=arbiter
Group=arbiter
WorkingDirectory=/home/arbiter/app
EnvironmentFile=/home/arbiter/.env
ExecStart=/home/arbiter/venv/bin/arbiter serve
Restart=on-failure
RestartSec=5
StartLimitIntervalSec=60
StartLimitBurst=5

# Hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/arbiter/data
PrivateTmp=true

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=arbiter

[Install]
WantedBy=multi-user.target
```

### Management commands

```bash
# Reload systemd after creating/editing the unit file
sudo systemctl daemon-reload

# Enable the service to start on boot
sudo systemctl enable arbiter

# Start the service
sudo systemctl start arbiter

# Check status
sudo systemctl status arbiter

# View logs (live)
sudo journalctl -u arbiter -f

# View last 100 log lines
sudo journalctl -u arbiter -n 100 --no-pager

# Restart after config changes
sudo systemctl restart arbiter

# Stop the service
sudo systemctl stop arbiter
```

### Log rotation

Systemd journal handles log rotation automatically. To configure retention:

```bash
# Edit /etc/systemd/journald.conf
sudo tee -a /etc/systemd/journald.conf > /dev/null << 'EOF'
SystemMaxUse=500M
MaxRetentionSec=30day
EOF

sudo systemctl restart systemd-journald
```

---

## PM2 (Node.js Process Manager)

PM2 can manage Python processes. This is useful if you already use PM2 for other services on the same machine.

### Prerequisites

```bash
# Install PM2 globally
npm install -g pm2

# Install Arbiter
pip install -e .   # or: pip install .
```

### Ecosystem file

Create `ecosystem.config.js` in the project root:

```javascript
module.exports = {
  apps: [
    {
      name: "arbiter",
      script: "arbiter",
      args: "serve",
      interpreter: "none",          // arbiter is a console_scripts entry point
      cwd: "/path/to/arbiter",      // adjust to your install path
      env: {
        BROKER_API_KEY: "your-secret-key-here",
        BROKER_BIND_HOST: "127.0.0.1",
        BROKER_BIND_PORT: "8081",
        BROKER_CORS_ORIGIN: "https://app.example.com",
        BROKER_RATE_LIMIT: "120",
        BROKER_RATE_WINDOW: "60",
        BROKER_MAX_BODY_SIZE: "1048576",
        BROKER_PROJECT_ID: "sir",
        BROKER_LOCAL_CACHE_PATH: "./.broker/cache",
        RUFLO_DB_PATH: ".swarm/memory.db",
        SUPERMEMORY_API_KEY: "",     // set if using Supermemory
      },
      autorestart: true,
      max_restarts: 10,
      restart_delay: 5000,          // 5 seconds between restarts
      watch: false,
      max_memory_restart: "200M",
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      error_file: "./logs/arbiter-error.log",
      out_file: "./logs/arbiter-out.log",
      merge_logs: true,
    },
  ],
};
```

If `arbiter` is inside a virtualenv and not on the global PATH, use the full path:

```javascript
      script: "/home/arbiter/venv/bin/arbiter",
```

### PM2 commands

```bash
# Start the service
pm2 start ecosystem.config.js

# Check status
pm2 status arbiter

# View logs
pm2 logs arbiter

# Restart after config changes
pm2 restart arbiter

# Stop
pm2 stop arbiter

# Set PM2 to start on boot
pm2 startup
pm2 save
```

### Log rotation with PM2

```bash
# Install the log-rotate module
pm2 install pm2-logrotate

# Configure rotation
pm2 set pm2-logrotate:max_size 50M
pm2 set pm2-logrotate:retain 10
pm2 set pm2-logrotate:compress true
pm2 set pm2-logrotate:dateFormat YYYY-MM-DD_HH-mm-ss
```

---

## Reverse Proxy (Nginx)

In production, place Arbiter behind a reverse proxy for TLS termination and additional security.

```nginx
server {
    listen 443 ssl http2;
    server_name arbiter.example.com;

    ssl_certificate     /etc/letsencrypt/live/arbiter.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/arbiter.example.com/privkey.pem;

    # Security headers
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;

    # Rate limiting at the proxy level (optional, complements broker-level limiting)
    limit_req_zone $binary_remote_addr zone=arbiter:10m rate=30r/s;
    limit_req zone=arbiter burst=20 nodelay;

    location / {
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Timeouts
        proxy_connect_timeout 10s;
        proxy_read_timeout 30s;
        proxy_send_timeout 30s;

        # Body size limit (matches BROKER_MAX_BODY_SIZE)
        client_max_body_size 1m;
    }

    # Public health check — bypass auth at proxy level if desired
    location = /health {
        proxy_pass http://127.0.0.1:8081/health;
    }
}

# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name arbiter.example.com;
    return 301 https://$host$request_uri;
}
```

---

## Security Checklist

Before exposing Arbiter to the network, verify each item:

### Authentication

- [ ] `BROKER_API_KEY` is set to a strong, random value (minimum 32 characters).
- [ ] The API key is stored only in the `.env` file or systemd `EnvironmentFile`, never in version control.
- [ ] The `.env` file has restricted permissions (`chmod 600`).

### Network

- [ ] `BROKER_BIND_HOST` is set to `127.0.0.1` (not `0.0.0.0`) when behind a reverse proxy.
- [ ] A reverse proxy (Nginx, Caddy, Traefik) terminates TLS in front of the broker.
- [ ] Firewall rules block direct access to port 8081 from the public internet.

### CORS

- [ ] `BROKER_CORS_ORIGIN` is set to the specific domain that needs access (not `*`).
- [ ] If no browser clients need access, set `BROKER_CORS_ORIGIN` to an empty string or a non-matching value.

### Rate Limiting

- [ ] `BROKER_RATE_LIMIT` is tuned for expected traffic. Default is 60 requests per 60-second window per IP.
- [ ] For high-traffic deployments, consider increasing the limit or adding proxy-level rate limiting.
- [ ] The `/health` endpoint is exempt from rate limiting (by design).

### Request Size

- [ ] `BROKER_MAX_BODY_SIZE` is set appropriately. Default 1 MB is sufficient for memory events. Reduce if you want tighter control.

### Secrets and API Keys

- [ ] `SUPERMEMORY_API_KEY` is set in the environment, not in any committed file.
- [ ] No secrets appear in `broker/config.json` or any file tracked by git.
- [ ] `.env` is listed in `.gitignore`.

### Logging and Monitoring

- [ ] Log rotation is configured (systemd journal retention or PM2 log-rotate).
- [ ] The `/metrics` endpoint is monitored or scraped periodically.
- [ ] Alerts are set up for high error rates or unexpected restarts.

### Container-Specific

- [ ] Named volumes or bind mounts are used for `.broker/cache` and `.swarm/memory.db` so data survives container restarts.
- [ ] The Docker image is rebuilt and redeployed when updating the broker code.
- [ ] The container runs as a non-root user (the Dockerfile uses the default `root` -- consider adding a `USER` directive for hardened deployments).

---

## Quick Reference

| Action | Command |
|--------|---------|
| Build Docker image | `docker build -t arbiter .` |
| Run with Docker | `docker run -d --name arbiter -p 8081:8081 --env-file .env -v arbiter-cache:/app/.broker/cache -v arbiter-swarm:/app/.swarm arbiter` |
| Run with Docker Compose | `docker compose up -d` |
| Start systemd service | `sudo systemctl start arbiter` |
| View systemd logs | `sudo journalctl -u arbiter -f` |
| Start with PM2 | `pm2 start ecosystem.config.js` |
| Health check | `curl http://localhost:8081/health` |
| Run tests | `python -m unittest discover tests -v` |
