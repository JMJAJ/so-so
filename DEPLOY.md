# Deploying NEXUS (Render + Supabase + Vercel, all free tiers)

```
browser ──> Vercel (static frontend, dist/client)
               │  /api/*  (rewrite in vercel.json)
               ▼
            Render free web service (FastAPI + scheduler)  <── cron-job.org pings /api/health every 10 min
               │  database snapshot every 15 min, after each job, on shutdown
               ▼
            Supabase Storage bucket "nexus" (nexus_v3.db.gz + 7 daily copies)
```

Render's free disk is wiped on every restart, deploy and spin-down, so the SQLite database
lives in Supabase Storage and is restored when the server boots (`server/nexus/snapshot.py`).
A free service also sleeps after 15 minutes without requests, which would stop the scheduler,
so an external pinger keeps it awake (one always-on service fits in Render's 750 free hours).

## 1. Supabase (storage for the database)

1. In your Supabase project: **Storage → New bucket**, name `nexus`, **private** (leave "Public" off).
2. **Project Settings → API**: copy the **Project URL** and the **service_role** key.
   The service_role key bypasses all access rules: put it only in Render's environment and your
   own shell, never in the frontend, `.env` files you commit, or chat.

## 2. Upload your current database as the starting point

This skips the 10-year download on Render and keeps your paper portfolio and track record.
In PowerShell, from the repo:

```powershell
cd server
$env:SUPABASE_URL = "https://YOUR-PROJECT.supabase.co"
$env:SUPABASE_SERVICE_KEY = "YOUR-SERVICE-ROLE-KEY"
python -m nexus snapshot push
```

It prints `"pushed": true` and the size (about 10 MB gzipped). Set the two variables only in
that shell, not in `server/.env`: a local backend with them set would also upload snapshots and
overwrite the cloud copy.

Also print your local encryption secret; Render needs it so API keys saved in Settings still
decrypt:

```powershell
Get-Content data\.secret
```

## 3. Render (backend)

1. **New → Blueprint**, connect GitHub repo `JMJAJ/investment-angel-bot`. Pick the branch with
   `render.yaml` (`v3-research-rebuild`, or `main` once the PR is merged).
2. Render reads `render.yaml` and asks for each secret:

   | Variable | Value |
   |---|---|
   | `NEXUS_PASSWORD` | the password for the website (long) |
   | `NEXUS_SECRET` | output of `Get-Content data\.secret` above |
   | `SUPABASE_URL` | Supabase Project URL |
   | `SUPABASE_SERVICE_KEY` | Supabase service_role key |
   | `NVIDIA_API_KEY` | your NVIDIA NIM key |
   | `FINNHUB_API_KEY` | your Finnhub key |
   | `FRED_API_KEY` | optional; leave empty if you don't have one |

3. Deploy. When it's live, open `https://nexus-api.onrender.com/api/health` (Render shows the
   exact URL; if the name was taken it has a suffix). You want
   `{"ok": true, "has_data": true, "snapshot": {"enabled": true, ...}}`.
   `has_data: false` means the snapshot wasn't found: check step 2 and the bucket name.

## 4. Vercel (frontend)

1. If Render's URL is not exactly `https://nexus-api.onrender.com`, edit the `/api` rewrite in
   `vercel.json` to your URL and push.
2. **Add New → Project**, import the same repo and branch. Vercel picks up `vercel.json`
   (build `npm run build`, output `dist/client`); no environment variables needed.
3. Open the Vercel URL and sign in with `NEXUS_PASSWORD`.

## 5. Keep it awake (cron-job.org)

Create a free account at https://cron-job.org, then **Create cronjob**:
URL `https://nexus-api.onrender.com/api/health`, every **10 minutes**. That's the only route that
works without logging in, and it exposes no data.

## What runs on its own (UTC)

| Job | When |
|---|---|
| fills, stops, targets, expiry | every 5 min (every minute while a browser is open) |
| news + classification | every 30 min |
| daily data, scoring, post-mortems | 21:45 |
| AI market brief and new calls | 22:30 |
| event studies, backtest, replay | Saturday 06:00 |

## Things to watch

- **Memory**: free instances have 512 MB. If the Saturday research job crashes the service
  (Render shows "Out of memory" events), run that job locally and push a snapshot, or upgrade
  the instance.
- **Yahoo**: yfinance sometimes rate-limits cloud IPs. Missing prices show up as stale quotes
  and `bars failed` in Settings → jobs.
- **Two copies**: after you deploy, your local database and the cloud one drift apart. To pull
  the cloud copy locally: set the two variables as in step 2 and run
  `python -m nexus snapshot pull` (it replaces your local database).
- **Restore an older day**: daily copies are kept in the bucket under `daily/`. Download one, then
  upload it as `nexus_v3.db.gz` and restart the service.
