#!/usr/bin/env bash
# Veyra: one-command setup for a fresh Ubuntu 22.04/24.04 server (e.g. Oracle Cloud Always Free, ARM or AMD).
#
#   curl -fsSL https://raw.githubusercontent.com/aryanpol73/veyra/main/deploy/setup-ubuntu.sh -o setup.sh
#   bash setup.sh
#
# Safe to re-run: it updates the code and restarts Veyra, keeping your .env and data.
set -euo pipefail

REPO="${VEYRA_REPO:-https://github.com/aryanpol73/veyra.git}"
DIR="${VEYRA_DIR:-$HOME/veyra}"
say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

[ "$(id -u)" -eq 0 ] && { echo "Run as your normal user (it uses sudo where needed), not root."; exit 1; }

say "Installing Docker (official repository)"
if ! command -v docker >/dev/null 2>&1; then
  sudo apt-get update -y
  sudo apt-get install -y ca-certificates curl gnupg git
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -y
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  sudo systemctl enable --now docker
fi
sudo usermod -aG docker "$USER" || true
DOCKER="docker"; docker info >/dev/null 2>&1 || DOCKER="sudo docker"   # group change applies at next login

say "Opening ports 80 and 443 in the server firewall"
# Oracle's Ubuntu images ship iptables rules that reject everything except SSH. (You ALSO need an ingress rule
# for 80/443 in the cloud console's security list; see the guide.)
for p in 80 443; do
  sudo iptables -C INPUT -p tcp --dport "$p" -j ACCEPT 2>/dev/null || sudo iptables -I INPUT 5 -p tcp --dport "$p" -j ACCEPT
done
sudo iptables -C INPUT -p udp --dport 443 -j ACCEPT 2>/dev/null || sudo iptables -I INPUT 5 -p udp --dport 443 -j ACCEPT
if command -v netfilter-persistent >/dev/null 2>&1; then sudo netfilter-persistent save; else
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent && sudo netfilter-persistent save; fi
command -v ufw >/dev/null 2>&1 && sudo ufw status | grep -q active && { sudo ufw allow 80/tcp; sudo ufw allow 443; }

if [ "$(awk '/MemTotal/ {print $2}' /proc/meminfo)" -lt 2000000 ] && ! swapon --show | grep -q .; then
  say "Adding 2 GB swap (small machine: the image build needs it)"
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
  grep -q /swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

say "Getting the Veyra code"
if [ -d "$DIR/.git" ]; then git -C "$DIR" pull --ff-only; else git clone "$REPO" "$DIR"; fi
cd "$DIR"

if [ ! -f .env ]; then
  say "Creating .env (your answers stay on this server)"
  cp .env.example .env
  set_env() { # key value: replace "KEY=..." or append
    if grep -q "^$1=" .env; then sed -i "s|^$1=.*|$1=$2|" .env; else echo "$1=$2" >> .env; fi
  }
  read -rp  "Domain pointing at this server (e.g. veyra-you.duckdns.org): " DOMAIN
  while :; do read -rsp "Admin password for the web app (10+ characters): " PW; echo; [ "${#PW}" -ge 10 ] && break; echo "Too short."; done
  read -rsp "Groq API key (Enter to skip): " GROQ; echo
  read -rsp "Gemini API key (Enter to skip): " GEMINI; echo
  read -rsp "OpenRouter API key (Enter to skip): " OPENROUTER; echo
  read -rsp "Mistral API key (Enter to skip): " MISTRAL; echo
  read -rp  "Contact email for the crawler's User-Agent: " EMAIL
  set_env VEYRA_DOMAIN "$DOMAIN"
  set_env VEYRA_ADMIN_PASSWORD "$PW"
  set_env VEYRA_SECRET_KEY "$(openssl rand -hex 32)"
  [ -n "$GROQ" ] && set_env GROQ_API_KEY "$GROQ"
  [ -n "$GEMINI" ] && set_env GEMINI_API_KEY "$GEMINI"
  [ -n "$OPENROUTER" ] && set_env OPENROUTER_API_KEY "$OPENROUTER"
  [ -n "$MISTRAL" ] && set_env MISTRAL_API_KEY "$MISTRAL"
  [ -n "$EMAIL" ] && set_env USER_AGENT_EMAIL "$EMAIL"
  chmod 600 .env
fi
grep -q "^VEYRA_DOMAIN=." .env || { echo "Set VEYRA_DOMAIN in $DIR/.env, then re-run."; exit 1; }

say "Building and starting Veyra (first build takes a few minutes)"
$DOCKER compose -f docker-compose.yml -f docker-compose.deploy.yml up -d --build

say "Waiting for Veyra to be healthy"
for _ in $(seq 1 60); do
  [ "$($DOCKER inspect -f '{{.State.Health.Status}}' veyra 2>/dev/null)" = healthy ] && break; sleep 3
done
$DOCKER ps --filter name=veyra --format '{{.Names}}: {{.Status}}'
$DOCKER exec veyra python -m app.llm_check || true

DOMAIN="$(grep '^VEYRA_DOMAIN=' .env | cut -d= -f2)"
say "Done. Open https://$DOMAIN (the HTTPS certificate is issued on the first visit; give it a minute)."
echo "Update later:  cd $DIR && git pull && docker compose -f docker-compose.yml -f docker-compose.deploy.yml up -d --build"
