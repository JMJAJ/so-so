# Deploying NEXUS (Render + Supabase + Vercel, all free tiers)

```
browser ──> Vercel (static frontend, dist/client)
               │  /api/*  (rewrite in vercel.json)
               ▼
            Render free web service (FastAPI + scheduler)  <── pings its own /api/health every 10 min
               │                                                (cron-job.org optional backup)
               │  database snapshot every 15 min, after each job, on shutdown
               ▼
            Supabase Storage bucket "nexus" (nexus_v3.db.gz + 7 daily copies)
```

Render's free disk is wiped on every restart, deploy and spin-down, so the SQLite database
lives in Supabase Storage and is restored when the server boots (`server/nexus/snapshot.py`).
A free service also sleeps after 15 minutes without requests, which would stop the scheduler,
so the server pings its own public URL every 10 minutes (`server/nexus/keepalive.py`, on
whenever Render sets `RENDER_EXTERNAL_URL`). One always-on service fits in Render's 750 free hours.

## 1. Supabase (storage for the database)

1. In your Supabase project: **Storage → New bucket**, name `nexus`, **private** (leave "Public" off).
2. **SQL Editor → New query**, run this once. It creates the heartbeat row the server updates
   every 6 hours: Supabase pauses free projects after a week without database activity, and
   snapshot uploads alone may not count.

   ```sql
   create table if not exists public.nexus_heartbeat (
     id int primary key,
     beat_at timestamptz not null default now(),
     note text
   );
   -- No policies: only the service_role key (the server) can read or write it.
   alter table public.nexus_heartbeat enable row level security;
   ```
3. **Project Settings → API**: copy the **Project URL** and the **service_role** key.
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

1. Create the service, either way:
   - **New → Blueprint**, connect GitHub repo `JMJAJ/TradeBot-alpha` and pick the branch with
     `render.yaml` (`main` once the PR is merged). Render reads `render.yaml` and asks for each secret.
   - **New → Web Service** (use this if the Blueprint asks for a credit card), same repo, with:

     | Field | Value |
     |---|---|
     | Name / Region / Branch | `nexus-api` / Frankfurt / `main` |
     | Root Directory | `server` |
     | Language | Python 3 |
     | Build Command | `pip install -r requirements.txt` |
     | Start Command | `uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1` |
     | Instance Type | **Free** |
     | Advanced → Health Check Path | `/api/health` |

     plus environment variables `PYTHON_VERSION=3.13.5` and `SNAPSHOT_BUCKET=nexus`.
2. The secrets (environment variables):

   | Variable | Value |
   |---|---|
   | `NEXUS_PASSWORD` | the website login password: you make it up (long and random, keep it in a password manager) |
   | `NEXUS_SECRET` | output of `Get-Content data\.secret` above |
   | `SUPABASE_URL` | Supabase Project URL |
   | `SUPABASE_SERVICE_KEY` | Supabase service_role key |
   | `NVIDIA_API_KEY` | your NVIDIA NIM key |
   | `FINNHUB_API_KEY` | your Finnhub key |
   | `FRED_API_KEY` | optional; leave empty if you don't have one |

3. Deploy. When it's live, open `https://nexus-api-01di.onrender.com/api/health` (Render shows the
   exact URL; if the name was taken it has a suffix). You want
   `{"ok": true, "has_data": true, "snapshot": {"enabled": true, "last_heartbeat": "...", ...}}`.
   `has_data: false` means the snapshot wasn't found: check step 2 and the bucket name.
   `last_heartbeat: null` means the heartbeat table is missing (step 1.2); Settings → logs shows why.

## 4. Vercel (frontend)

1. If Render's URL is not exactly `https://nexus-api-01di.onrender.com`, edit the `/api` rewrite in
   `vercel.json` to your URL and push.
2. **Add New → Project**, import the same repo and branch. Vercel picks up `vercel.json`
   (build `npm run build`, output `dist/client`); no environment variables needed.
3. Open the Vercel URL and sign in with `NEXUS_PASSWORD`.

## 5. Keep it awake

Nothing to do: on Render the server pings its own `/api/health` every 10 minutes, which counts
as inbound traffic and resets the 15-minute sleep timer. `/api/health` shows
`"keepalive": {"enabled": true, "last_ping": "..."}` once it has run. Set `KEEPALIVE_MINUTES=0`
to turn it off.

**Optional backup (recommended):** a self-ping can't wake the service if it ever goes down anyway
(a crash, for example running out of memory, or a Render restart), and the scheduler is down with it. A free
https://cron-job.org job calling `https://nexus-api-01di.onrender.com/api/health` every **10
minutes** wakes it from outside. That's the only route that works without logging in, and it
exposes no data.

## 6. Research on GitHub Actions (free, keeps Render under 512 MB)

The Saturday research job (event studies, backtest, replay, simulation check) is too heavy for
Render's free instance, so it runs on GitHub's runners (`.github/workflows/research.yml`):

1. GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**: add
   `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` (the same values as on Render). Secrets are hidden
   from logs and from forks, even on a public repo. If your bucket isn't `nexus`, add a
   repository **variable** `SNAPSHOT_BUCKET`.
2. Render already has `NEXUS_RESEARCH_REMOTE=1` (from `render.yaml`; add it by hand if you set the
   service up manually). With it, the server stops running research itself and checks every 15
   minutes for a newer bundle to import.
3. Run it once now: repo → **Actions → research → Run workflow**. When it's green, within 15
   minutes Settings → jobs shows `research_import` ok.

The workflow pulls the latest snapshot as a **read-only** copy (`NEXUS_SNAPSHOT_READONLY=1` stops
it ever being pushed back), runs the research and uploads only the research tables to
`research/latest.db.gz`. The server merges those tables in one transaction. Paper trades,
recommendations, news and settings are never in the bundle, so nothing recorded during the run is
lost. A run that produced no event studies or models is refused on both sides.

## What runs on its own (UTC)

| Job | When |
|---|---|
| fills, stops, targets, expiry | every 5 min (every minute while a browser is open) |
| breaking-news wire | about every minute |
| news + classification | every 10 min |
| daily data, scoring, post-mortems | 21:45 |
| AI market brief and new calls | 22:30 |
| event studies, backtest, replay | Saturday 06:00 on GitHub Actions; imported within 15 min |

## Things to watch

- **Supabase pausing**: if Supabase still emails a pause warning, open the project dashboard once
  (that counts as activity) and check that `nexus_heartbeat.beat_at` is recent.
- **Memory**: free instances have 512 MB. Research runs on GitHub Actions for this reason (step 6).
  Without `NEXUS_RESEARCH_REMOTE=1` it runs on Render and may crash it ("Out of memory" events).
- **Yahoo**: yfinance sometimes rate-limits cloud IPs. Missing prices show up as stale quotes
  and `bars failed` in Settings → jobs.
- **Two copies**: after you deploy, your local database and the cloud one drift apart. To pull
  the cloud copy locally: set the two variables as in step 2 and run
  `python -m nexus snapshot pull` (it replaces your local database).
- **Restore an older day**: daily copies are kept in the bucket under `daily/`. Download one, then
  upload it as `nexus_v3.db.gz` and restart the service.
