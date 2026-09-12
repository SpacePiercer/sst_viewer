# Deploying sst_viewer to sst.georgiikuzhel.com

Run everything here **on the Hostinger VPS** as a sudo-capable user.
Nothing in this file needs to be run on the Windows PC.

## 0. Pre-flight

```bash
free -h          # want >= 3 GB free
df -h /          # want >= 10 GB free
docker --version # install below if missing
```

## 1. Harden the box

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y unattended-upgrades ufw
sudo dpkg-reconfigure --priority=low unattended-upgrades

# SSH by key only -- do this while your key already works, and keep the
# current session open until a second one logs in successfully.
sudo sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart ssh

sudo ufw allow 22/tcp && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
sudo ufw enable && sudo ufw status
```

Port 8000 is deliberately **not** opened: the app binds to 127.0.0.1 and is
reachable only through Caddy.

## 2. Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"   # log out and back in for this to take effect
```

## 3. The app

```bash
sudo mkdir -p /srv && sudo chown "$USER" /srv && cd /srv
git clone git@github.com:SpacePiercer/sst_viewer.git   # needs a deploy key
cd sst_viewer

# Writable state, owned by the container's uid (10001). These files must
# EXIST before the first `up`, or Docker creates directories in their place.
mkdir -p state/library state/cache state/oisst
: > state/users.json ; : > state/secret.key ; echo '[]' > state/areas.json
sudo chown -R 10001:10001 state

docker compose up -d --build
curl -si localhost:8000/ | head -3      # expect 303 -> /login
```

## 4. Caddy (HTTPS)

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy

sudo tee /etc/caddy/Caddyfile >/dev/null <<'CADDY'
sst.georgiikuzhel.com {
    reverse_proxy 127.0.0.1:8000
}
CADDY
sudo systemctl reload caddy
```

Do this **after** the DNS record below resolves, or certificate issuance fails
and Caddy backs off for a while.

## 5. DNS (Bluehost cPanel -> Zone Editor)

One A record: `sst` -> the VPS IPv4 address. Nothing else on
`georgiikuzhel.com` changes. Check with `dig +short sst.georgiikuzhel.com`
before reloading Caddy.

## 6. Accounts

```bash
docker compose exec app python scripts/users.py add georgii
docker compose exec app python scripts/users.py add konstantin
docker compose exec app python scripts/users.py add polina
docker compose exec app python scripts/users.py list
```

Each password is typed at a hidden prompt. It never appears in a command, in
shell history, or in any log.

## 7. Backups

```bash
sudo tee /etc/cron.daily/sst-backup >/dev/null <<'CRON'
#!/bin/sh
# Kilobytes, not gigabytes: accounts, the signing key, saved areas, and each
# user's generated reports. Losing library/users/ loses real work; losing
# secret.key only signs everyone out.
set -e
d=/srv/sst_viewer/backups
mkdir -p "$d"
tar -czf "$d/sst-$(date +%F).tgz" -C /srv/sst_viewer/state \
    users.json secret.key areas.json library/users 2>/dev/null || true
find "$d" -name 'sst-*.tgz' -mtime +14 -delete
CRON
sudo chmod +x /etc/cron.daily/sst-backup
```

## 8. Optional: a little data to look at

Both remote datasets live on `coastwatch.pfeg.noaa.gov`, which has been down
since 2026-09-11. Until it returns the site authenticates fine but draws
nothing. To have something on screen, copy a handful of local OISST files
(~1.5 MB each) from the Windows PC:

```powershell
scp (Get-ChildItem "data\oisst_may20_july1\oisst-avhrr-v02r01.202506*.nc" |
     Select-Object -First 10).FullName user@VPS:/srv/sst_viewer/state/oisst/
```

then `sudo chown -R 10001:10001 state/oisst && docker compose restart`.

## Updating later

```bash
cd /srv/sst_viewer && git pull && docker compose up -d --build
```

Sessions survive it: the cookie is signed, not stored server-side.
