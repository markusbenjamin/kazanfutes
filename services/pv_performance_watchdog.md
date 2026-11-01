# Running the PV performance watchdog

The scheduled entry point is `services/pv_performance_watchdog.py`. It uses the
frozen `pv_accumulation_model_2025.json` and the existing `notify_admin` email
route. No recipient or SMTP credential is embedded in the new code. The
underlying replay/shadow commands continue to send no notifications themselves.

The timer runs at **07:15, 13:15 and 19:15 Pi local time**, with up to a minute
of random delay. The Pi is configured for Europe/Budapest. The extra runs retry
delayed weather and email delivery; unchanged state produces no repeated email.

On first activation the service catches up from 1 January 2026 and sends one
summary of current inspections and coverage limitations. It suppresses emails
about historical incidents already resolved. Subsequent runs email new
inspections, recoveries, and changes in monitoring coverage. This is an
inspection aid: cause and physical string labels remain unconfirmed.

State is kept outside the Git checkout, in `/var/lib/kazanfutes-pv-watchdog`:

- `evidence_state.json`: separate array and relative-input cursors and incidents.
- `latest_report.json`: complete latest decision report, coverage and delivery status.
- `notifications.json`: acknowledged events and durable pending email messages.

Files are private to the service user. A failed send leaves the message pending
and fails the service run; the next timer run retries it. The existing service
watchdog also watches this unit. The event journal covers a crash between
scoring and creating the notification. A crash after SMTP acceptance but before
saving acknowledgement can duplicate an email; delivery favors avoiding misses.

Normal checks process relative evidence through yesterday and independent
weather evidence with a seven-day lag. PV6/PV8 relative checks are unavailable
until a separately validated model has enough calibration support. No rolling
retraining can silently normalize a newly occurring loss.

Install after pulling the reviewed code:

```sh
sudo install -m 0644 services/systemd/pv_performance_watchdog.service /etc/systemd/system/
sudo install -m 0644 services/systemd/pv_performance_watchdog.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pv_performance_watchdog.timer
sudo systemctl start pv_performance_watchdog.service
```

Inspect operation:

```sh
systemctl status pv_performance_watchdog.timer --no-pager
journalctl -u pv_performance_watchdog.service -n 80 --no-pager
cat /var/lib/kazanfutes-pv-watchdog/latest_report.json
```

`python -B -m services.pv_performance_watchdog --dry-run` recomputes a preview
without writes or emails. A different frozen model needs an explicitly separate
runtime directory; do not delete the existing state to hide an open inspection.
To stop scheduled checks, disable this timer. No other device or heating service
needs to be stopped or restarted.

See `pv_accumulation_validation.md` for the known-event replay, limitations,
previous failures, and measured alert burden. The March case influenced
development and does not establish an unbiased fault-detection rate.

## Deployment record: 1 November 2026

The implementation was published on `main` at
`3f3d0cd337d2f46257773ef99ef37dc0d3b19d6b` through the approved project sync
routine in a clean sparse checkout. The existing Windows worktree and unrelated
edits were preserved. The Pi fast-forwarded to that commit under its repository
sync lock, and all 64 tests passed there as well as locally.

The timer was enabled and its first service run completed successfully at
20:03:31 CET. The admin SMTP route accepted the activation email; the durable
outbox was empty afterward. Open inspections were the array and logged PV1/PV2.
An immediate second run left the sent count at one and the outbox empty,
confirming that unchanged state did not send a duplicate. The timer reported
`enabled`, `active (waiting)`, with its next run at 07:15:28 CET on 2 November.
The frozen model remained
`87d4dc0625aa9068e51bb2c8d175ab4421f060fcc761ac140fd8cb876ec6fdf8`.

The project filesystem is an active ext4 mount at `/media/pi/program_stick`,
generated from `/etc/fstab`. For offline unit checks on this Pi, use
`systemd-analyze --generators=yes verify ...`; without generators, the verifier
incorrectly reports the runtime mount dependency as missing. No mount, heating
service or deCONZ restart was needed.
