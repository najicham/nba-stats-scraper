# 🏀 Sports Scraper (Python + Google Cloud Functions)

This project scrapes sports data (e.g., NBA props), stores results in Google Cloud Storage, and supports both local testing and deployment via Google Cloud Functions.

---

## 📁 Project Structure

```
scrape-sports-25/
├── functions/                           # Cloud Function code
│   └── scrape.py
├── requirements.txt                     # Python dependencies
├── venv-scrape-sports-25/               # Local virtualenv (ignored)
├── data/                                # (Optional) local output
├── scripts/
│   ├── create_gcloud_configs.sh         # GCP config setup
│   ├── deploy_functions.sh              # Cloud Functions deploy
│   ├── manage_schedulers.sh             # Scheduler setup (optional)
│   ├── Makefile                         # Task runner (optional)
│   ├── service-account-key.json         # 🔐 Firebase/GCP key (ignored)
│   └── python/
│       ├── env_create.sh
│       ├── env_activate.sh
│       ├── install_deps.sh
│       ├── freeze_requirements.sh
│       └── check_env.sh                # ✅ Environment validation
└── .gcloudignore                        # Prevents uploading venv/key/etc
```

---

## 📦 Python Environment Setup (Local Dev)

Scripts in `scripts/python/` manage your environment.

### 1. Create Virtual Environment

```bash
./scripts/python/env_create.sh
```

Creates `venv-scrape-sports-25/` at the root.

---

### 2. Activate Virtual Environment

```bash
source ./scripts/python/env_activate.sh
```

---

### 3. Install Dependencies

```bash
./scripts/python/install_deps.sh
```

---

### 4. Save Installed Packages

```bash
./scripts/python/freeze_requirements.sh
```

---

### ✅ Validate Setup

Check if everything is ready (Python, venv, key, etc):

```bash
./scripts/python/check_env.sh
```

---

## 📜 Recommended Python Packages

Your `requirements.txt` might include:

```
google-cloud-storage
functions-framework
requests
beautifulsoup4
lxml
```

---

## ☁️ Google Cloud Setup

### 1. Set config

```bash
gcswitch sports
```

### 2. Create GCS bucket

```bash
gcloud storage buckets create sports-scraper-data \
  --location=us-west2 \
  --uniform-bucket-level-access
```

---

## 🔐 Service Account Key

Place your JSON key at:

```bash
scripts/service-account-key.json
```

> ⚠️ This file is ignored by `.gitignore`/`.gcloudignore`.

### On a new machine:
1. Go to [IAM & Admin > Service Accounts](https://console.cloud.google.com/iam-admin/serviceaccounts)
2. Find or create the service account for `urcwest`
3. Add a key → JSON → Download → Rename → Drop it in `scripts/`

---

## 🧠 Cloud Function Code (`functions/scrape.py`)

```python
import datetime
import json
from google.cloud import storage

def scrape_data(request):
    scraped = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "player_stats": [
            {"name": "John Doe", "points": 22},
            {"name": "Jane Smith", "points": 19}
        ]
    }

    bucket_name = "sports-scraper-data"
    filename = f"scrapes/{datetime.datetime.utcnow().isoformat()}.json"
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(filename)
    blob.upload_from_string(json.dumps(scraped), content_type="application/json")

    return f"Saved scrape to {filename}"
```

---

## 🚀 Deploy to Google Cloud

### Manual CLI:

```bash
gcloud functions deploy scrape_data \
  --runtime=python310 \
  --trigger-http \
  --allow-unauthenticated \
  --source=functions \
  --entry-point=scrape_data \
  --project=scrape-sports-25 \
  --region=us-west2
```

### Script:

```bash
./scripts/deploy_functions.sh
```

---

## 🧪 Local Testing

```bash
functions-framework --target=scrape_data --debug
curl http://localhost:8080
```

---

## 🧹 Cleanup

```bash
gcloud functions delete scrape_data --region=us-west2
gcloud storage buckets delete sports-scraper-data
```

---

## 📎 Resources

- [Google Cloud Functions](https://cloud.google.com/functions/docs)
- [Python Client: GCS](https://pypi.org/project/google-cloud-storage/)
- [Functions Framework](https://github.com/GoogleCloudPlatform/functions-framework-python)
- [BeautifulSoup Docs](https://www.crummy.com/software/BeautifulSoup/bs4/doc/)
