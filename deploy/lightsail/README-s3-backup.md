# belleliteaccounts → S3 cold backup (every 6 hours, 30-day auto-delete)

## Why S3 Standard (not Glacier storage class)

For **30-day auto-delete**, Glacier storage classes are *more expensive*:
- Glacier Instant / Flexible Retrieval: **90-day** minimum billable storage
- Glacier Deep Archive: **180-day** minimum billable storage

Deleting at day 30 still bills the minimum period (early-deletion charge).  
With a ~1 MB DB and 4 backups/day, **S3 Standard + expire at 30 days** is the lowest cost (fractions of a cent/month) and still uses Amazon S3 (same platform as Glacier).

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
