# belleliteaccounts WhatsApp daily sales cron (11:59 PM IST)

## Why crontab (not gunicorn)
The sales WhatsApp job is a CLI script. Gunicorn does not run it. Scheduling lives in **ubuntu crontab**, which is **outside** the app git tree, so normal `git pull` / code deploys **do not remove** the cron line.

## Install once on Lightsail
```bash
cd /home/ubuntu/belleliteaccounts
chmod +x deploy/lightsail/install_whatsapp_sales_cron.sh
./deploy/lightsail/install_whatsapp_sales_cron.sh
crontab -l | grep belleliteaccounts-whatsapp-sales
```

## After every code deploy
- Restart gunicorn for Python changes as usual.
- **Do not** wipe crontab.
- Re-run the installer only if the app path or venv path changed.

## Required `.env` (already on prod if configured)
```
WHATSAPP_SALES_REPORT_TEMPLATE=hotel_sales_update
WHATSAPP_SALES_REPORT_TEMPLATE_LANGUAGE=en
WHATSAPP_SALES_REPORT_RECIPIENTS=+918940651222,+919150000267,+919531825665,+919933268361,+917900003192,+919932081325
WHATSAPP_SALES_REPORT_SCHEDULE=1
WHATSAPP_SALES_REPORT_SCHEDULE_TIME=23:59
WHATSAPP_SALES_REPORT_SCHEDULE_TZ=Asia/Kolkata
```
Leave `WHATSAPP_DRY_RUN` unset/false on production.

## Localhost / Mac
Do **not** run a second live nightly cron against the same Meta WABA while Lightsail owns production sends. On Mac set `WHATSAPP_SALES_REPORT_SCHEDULE=0` (or remove the Mac crontab line).
