# belleliteaccounts → S3 cold backup (every 6 hours, 30-day auto-delete)

## Storage class: Glacier Deep Archive

Uploads use `BACKUP_S3_STORAGE_CLASS=DEEP_ARCHIVE`.

Lifecycle still expires objects after **30 days**. Note AWS Deep Archive has a
**180-day minimum billable storage** period, so deleting at day 30 incurs an
early-deletion charge for the remaining days.

## Safety (no website impact)

- Uses SQLite **online backup API** (consistent copy while app runs)
- Does **not** restart `belleliteaccounts`, nginx, or change `.env` / firewall / DNS
- Lives under `/home/ubuntu/belleliteaccounts-backup/` (outside the app git tree)
- Cron only **adds** one job; existing Neeraj Textile cron jobs stay untouched
- New private S3 bucket + IAM user limited to that bucket prefix only

## One-time AWS setup (CloudShell)

1. Open CloudShell in the AWS console (Mumbai / `ap-south-1`).
2. Paste and run `setup_s3_backup_cloudshell.sh`.
3. Copy the printed `credentials.env` contents securely to the agent or place the file on the server at:
   `/home/ubuntu/.belleliteaccounts-backup/credentials.env` (mode `600`).

## Install on Lightsail

```bash
# from Mac (example)
scp -i LightsailDefaultKey-ap-south-1.pem -r deploy/lightsail \
  ubuntu@SERVER:/home/ubuntu/belleliteaccounts-backup
# then on server:
chmod +x /home/ubuntu/belleliteaccounts-backup/*.sh
# place credentials.env, then:
/home/ubuntu/belleliteaccounts-backup/install_s3_backup_cron.sh
/home/ubuntu/belleliteaccounts-backup/run_s3_backup.sh
```

Schedule: `0 */6 * * *` (every 6 hours).

## Web app process (not started here)

This folder only installs the S3 backup cron. The Lightsail app itself should run with `FLASK_DEBUG=0`.
