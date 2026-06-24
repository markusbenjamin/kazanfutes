# Raspberry Pi Dev API Handoff

This is the compact handoff for reconnecting to the Raspberry Pi that should host the dev DuckDB API server for testing.

Keep this setup private:

- use Tailscale/local-only access
- do not expose the API publicly
- do not proceed to installation until access is confirmed
- stop and report clearly if SSH, username, sudo, Tailscale authorization, or the local database file is missing

## Verified Target

Last verified: 2026-06-24

Raspberry Pi candidate:

- Tailscale name: `phoscon`
- Tailscale IP: `100.124.103.116`
- SSH user: `pi`
- Hostname after login: `phoscon`
- Working directory after login: `/home/pi`

Tailscale reachability was confirmed through DERP:

- `DERP(nue)`
- direct connection was not established

This is still private Tailscale access, not public exposure.

Known SSH host key fingerprint:

- ED25519: `SHA256:YFrJL0yIGIexdwlsEYyzXQw05pUwWHYnB7aFc6/MVyY`

Do not store the Pi password in this repository.

## Local Prerequisites

Run these from the local Windows machine, not a cloud-only GitHub environment.

Required local commands:

- `tailscale`
- `ssh`
- `scp`

Previously observed paths:

- `ssh`: `C:\Windows\System32\OpenSSH\ssh.exe`
- `scp`: `C:\Windows\System32\OpenSSH\scp.exe`
- optional `plink`: `C:\Program Files\PuTTY\plink.exe`

Required local database file:

- `dev/db/store/observations.duckdb`

## Streamlined Access Check

From the repository root:

```powershell
tailscale status
```

Expected relevant node:

```text
100.124.103.116  phoscon  ...  linux  active
```

Ping the Pi over Tailscale:

```powershell
tailscale ping --timeout=10s phoscon
```

Expected useful result:

```text
pong from phoscon (100.124.103.116) via DERP(nue)
```

It is acceptable if the final line says:

```text
direct connection not established
```

Check local SSH/SCP tools:

```powershell
Get-Command ssh -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
Get-Command scp -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
```

Check the local DuckDB file:

```powershell
Test-Path -LiteralPath 'dev/db/store/observations.duckdb'
```

Expected:

```text
True
```

Check SSH login:

```powershell
ssh pi@phoscon "hostname; whoami; pwd"
```

Expected:

```text
phoscon
pi
/home/pi
```

Check sudo without making changes:

```powershell
ssh pi@phoscon 'sudo -n true; echo sudo_exit:$?'
```

Expected:

```text
sudo_exit:0
```

If this prints a sudo password error, stop and ask the user to run:

```powershell
ssh -t pi@phoscon "sudo -v"
```

## Non-Interactive Windows Probe

If OpenSSH password prompting is awkward in the agent environment, PuTTY `plink` can be used with an explicit host-key pin.

Use a password placeholder. Do not write the real password into scripts or docs.

```powershell
plink -batch -hostkey SHA256:YFrJL0yIGIexdwlsEYyzXQw05pUwWHYnB7aFc6/MVyY -pw <PI_PASSWORD> pi@phoscon "hostname; whoami; pwd"
```

Sudo check:

```powershell
plink -batch -hostkey SHA256:YFrJL0yIGIexdwlsEYyzXQw05pUwWHYnB7aFc6/MVyY -pw <PI_PASSWORD> pi@phoscon 'command -v sudo; sudo -n true; echo sudo_exit:$?'
```

Expected:

```text
/usr/bin/sudo
sudo_exit:0
```

## Stop Conditions

Stop before installation and report the exact blocker if any of these fail:

- `tailscale status` cannot access the local Tailscale service
- `phoscon` is missing or not active in `tailscale status`
- `tailscale ping phoscon` cannot get pongs
- SSH to `pi@phoscon` fails
- `scp` is missing locally
- `sudo -n true` fails and the user has not confirmed sudo access
- `dev/db/store/observations.duckdb` is missing locally

## Next Deployment Inputs

Only after access is confirmed, the next setup pass can handle:

- copying `dev/db/store/observations.duckdb` to the Pi
- confirming the synced repo path on the Pi
- installing or selecting the Python runtime/dependencies
- running `dev/db/db_server.py` bound to a local/Tailscale-only interface
- testing the API through Tailscale

Keep the API private. Prefer binding to localhost plus an SSH tunnel, or to the Pi's Tailscale IP only if direct Tailscale access is intentionally required.
