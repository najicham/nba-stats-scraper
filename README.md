# 🏀 Sports Scraper (Python + Google Cloud Functions)

This repository deploys one or more **Python web‑scraper functions** to **Google Cloud Functions Gen 2**, stores results in **Google Cloud Storage**, and (optionally) triggers them on a schedule with **Cloud Scheduler**.

---

## 📁 Project structure

```text
sports_scraper/
├── functions/               # One sub‑folder per Cloud Function (scraper)
│   ├── players/             # ↳ functions/players/scrape_players.py
│   └── props/               # ↳ functions/props/scrape_props.py
│
├── scripts/                 # 100 % idempotent helper scripts
│   ├── create_gcloud_configs.sh   # sets up/refreshes gcloud configs & accounts
│   ├── deploy_functions.sh        # deploys only the functions whose code changed
│   ├── manage_schedulers.sh       # create/update Cloud Scheduler jobs
│   └── Makefile                   # convenience wrapper: make deploy / schedule
│   └── urcwest‑*.json            # **Service‑account key – ignored by Git**
│
├── requirements.txt         # Shared Python deps
├── .gcloudignore            # Prevents junk from being uploaded at deploy time
└── README.md
```

> **Service‑account key** lives in `scripts/` and is ignored via `.gitignore` to avoid accidental commits.

---

## 🌐 Google Cloud bootstrap (one‑time)

1. **Generate gcloud configurations + credentials** (creates `main`, `sports`, `urcwest`).

   ```bash
   cd scripts
   ./create_gcloud_configs.sh           # ← edit project IDs inside first
   ```

   * `main` and `sports` use **your user** `nchammas@gmail.com`.
   * `urcwest` activates the **service‑account key** `urcwest‑….json`.
   * Default Functions / Cloud Run region is **`us‑west2` (Los Angeles)**.

2. **Activate the config for this repo** (once per shell):

   ```bash
   gcloud config configurations activate sports
   ```

3. **Enable required APIs** (only once per project):

   ```bash
   gcloud services enable \
       cloudfunctions.googleapis.com \
       cloudbuild.googleapis.com     \
       cloudscheduler.googleapis.com
   ```

4. **Create a GCS bucket for output (replace if you picked another name)**

   ```bash
   gcloud storage buckets create sports‑scraper‑data \
     --location=us‑west2 \
     --uniform-bucket-level-access
   ```

---

## 🛠️ Local Python env (optional)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Run scrapers locally with the same credentials:

```bash
export GOOGLE_APPLICATION_CREDENTIALS="$(pwd)/scripts/urcwest‑76e11c72b562.json"
python functions/players/scrape_players.py
```

---

## 🚀 Deployment workflow

### 1 · Deploy only changed functions

```bash
make deploy          # shortcut for ./scripts/deploy_functions.sh
```

* Uses **`git diff origin/main`** to skip functions whose folders are unchanged, saving Cloud Build minutes.
* Each function is deployed with `--service‑account=scraper‑exec@urcwest.iam.gserviceaccount.com` for least privilege.

### 2 · Create / update Cloud Scheduler jobs

```bash
make schedule        # shortcut for ./scripts/manage_schedulers.sh
```

* Jobs are defined in an associative array inside `manage_schedulers.sh`.
* Script is *idempotent*: first run → `create`, subsequent runs → `update`.

### 3 · All‑in‑one

```bash
make                 # runs both deploy and schedule targets
```

> **Region**: all `gcloud functions` and `gcloud scheduler` commands default to `us‑west2` because the config created in step 1 sets `functions/region` and `run/region` globally.

---

## 🧪 Smoke test after deploy

```bash
curl https://us‑west2‑scrape‑sports‑25.cloudfunctions.net/scrape_players
```

or via gcloud:

```bash
gcloud functions call scrape_players --region=us‑west2
```

---

## 🗓️ Cron schedule reference

| Job name        | Function         | Schedule (cron) | Purpose               |
| --------------- | ---------------- | --------------- | --------------------- |
| `daily-players` | `scrape_players` | `0 6 * * *`     | 06:00 PT daily scrape |
| `daily-props`   | `scrape_props`   | `30 6 * * *`    | 06:30 PT daily scrape |

Modify the associative array in `manage_schedulers.sh` to add more.

---

## ✅ Good practice checklist

* [x] `*.json` ignored in **.gitignore** → service‑account key never committed.
* [x] `gcloud config set functions/region us‑west2` baked into each config.
* [x] Least‑privilege **service account** attached to every Cloud Function (`--service-account`).
* [x] **Idempotent scripts** → safe to run any number of times.
* [x] Separate **deploy** and **schedule** logic; both callable via **Makefile**.

---

## 🧹 Cleanup

```bash
# Remove Cloud Functions
for f in scrape_players scrape_props; do
  gcloud functions delete "$f" --region=us‑west2 --quiet
done

# Remove Cloud Scheduler jobs
for j in daily-players daily-props; do
  gcloud scheduler jobs delete "$j" --location=us‑west2 --quiet
done

# Delete bucket
gcloud storage buckets delete sports‑scraper‑data --quiet
```

---

## 📎 Resources

* [Google Cloud Functions (GA Python 3.12)](https://cloud.google.com/functions/docs)
* [Google Cloud Scheduler](https://cloud.google.com/scheduler/docs)
* [Python Client for GCS](https://pypi.org/project/google-cloud-storage/)
