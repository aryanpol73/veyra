# Deploying Veyra publicly (free)

The target is **Oracle Cloud Always Free**: a permanently free Ubuntu server that stays on, with a persistent disk.
Veyra needs both: it checks competitors every 6 hours and sends push alerts even when no one has the app open, and
it keeps its database on disk. Free tiers that sleep or have no disk, such as Render's, can't run it.

Expect about 30 minutes, most of it creating accounts.

```
phone / laptop ──HTTPS──▶ Caddy (automatic Let's Encrypt certificate) ──▶ Veyra container ──▶ /data volume
                                                                   └──▶ free LLM APIs, Web Push services
```

## 1. Create the server (Oracle Cloud)

1. Sign up at <https://www.oracle.com/cloud/free/>. Oracle asks for a card **to verify your identity**; Always Free
   resources are not charged. Pick a **home region** near you; it can't be changed later.
2. Console → **Compute → Instances → Create instance**:
   - **Image:** Ubuntu 24.04 (or 22.04)
   - **Shape:** *Ampere* `VM.Standard.A1.Flex`, **2 OCPU / 12 GB** (inside the free allowance). If it says "out of
     capacity", retry later or pick the free AMD `VM.Standard.E2.1.Micro`; the setup script adds swap for that one.
   - **SSH keys:** upload your public key (or let Oracle generate one and download it).
   - **Networking:** keep "Assign a public IPv4 address" on.
3. Note the instance's **public IP address**.
4. Open the web ports. Instance → its **subnet** → **Security List** → **Add Ingress Rules**:
   - Source `0.0.0.0/0`, TCP, destination port `80`
   - Source `0.0.0.0/0`, TCP, destination port `443`
   - Source `0.0.0.0/0`, UDP, destination port `443` (optional, enables HTTP/3)

## 2. Get a free domain (DuckDNS)

HTTPS certificates need a domain name.

1. Go to <https://www.duckdns.org>, sign in (GitHub/Google), and create a subdomain such as `veyra-yourname`.
2. Set its **current ip** to the server's public IP and press **update ip**.

You now have `veyra-yourname.duckdns.org`. (A domain you already own works too: point an `A` record at the IP.)

## 3. Install Veyra on the server

From your PC (PowerShell; use the key path from step 1):

```bash
ssh -i path\to\your-key ubuntu@SERVER_IP
```

Then, on the server:

```bash
curl -fsSL https://raw.githubusercontent.com/aryanpol73/veyra/main/deploy/setup-ubuntu.sh -o setup.sh
```
```bash
bash setup.sh
```

The script installs Docker, opens ports 80/443 in Ubuntu's firewall, downloads Veyra, and asks for:
- your domain
- an admin password
- your free LLM keys (Groq / Gemini / OpenRouter / Mistral)
- a contact email

It generates the secret key itself and starts everything. The first build takes about 5 to 10 minutes on the free
server.

## 4. Open it and install it

- Open **https://veyra-yourname.duckdns.org** and sign in. The certificate is issued on the first visit, so give it
  a minute if the first load fails.
- **Phone:** Android Chrome → menu → **Install app**. iPhone Safari → **Share → Add to Home Screen**, then open it
  from the icon.
- **Notifications:** Overview → **Notifications → Enable**, then **Send test notification**, once on each device.
- **Competitors:** add them with **Add competitor → Discover**.

## Day-to-day

| Task | Command (on the server, in `~/veyra`) |
|---|---|
| Update to the latest version | `git pull && docker compose -f docker-compose.yml -f docker-compose.deploy.yml up -d --build` |
| Logs | `docker logs -f veyra` (proxy: `docker logs -f veyra-caddy`) |
| Check the LLM keys | `docker exec veyra python -m app.llm_check` |
| Change keys/settings | `nano .env`, then the update command above |
| Back up data | `docker run --rm -v veyra_veyra-data:/data -v "$PWD":/b alpine tar czf /b/veyra-backup.tgz -C /data .` |
| Stop | `docker compose -f docker-compose.yml -f docker-compose.deploy.yml down` (data is kept) |

Download a backup to your PC with `scp -i path\to\your-key ubuntu@SERVER_IP:~/veyra/veyra-backup.tgz .`

## Good to know

- **Idle reclamation:** Oracle may reclaim Always Free instances that stay idle for a week (CPU, network and memory
  all very low). Veyra's scheduled checks create some activity, but if Oracle warns you, upgrading the account to
  *Pay As You Go* stops reclamation. Always Free resources stay free on that plan; set a budget alert of $1 to be sure.
- **If the domain's IP changes:** for example, after recreating the instance, update it on DuckDNS.
- **Security:** only ports 80/443 (Caddy) and 22 (SSH) are open. Veyra itself has no public port, runs as a non-root
  user on a read-only filesystem, and refuses to start without a strong admin password and secret key. Keep `.env`
  private (the script sets it to `chmod 600`).
- **Free LLM limits** still apply. The app fails over between providers on its own, and more keys mean more capacity.
