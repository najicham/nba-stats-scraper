# Dev Ops Pocket Guide  
*(place this file at **`bin/README.md`** so it lives next to the helper scripts)*

---

## 1  Helper scripts in `bin/`

### **build_image.sh** — build & push container  
```bash
# Build mutable “dev” tag
./bin/build_image.sh dev

# Build immutable tag based on current Git commit
./bin/build_image.sh $(git rev-parse --short HEAD)
````

*Environment overrides*
`PROJECT` (default *nba‑props‑platform*), `REGION` (*us‑west2*), `TAG` (first arg).
On success, the script writes the full image URI to **`.last_image`**.

---

### **deploy\_run.sh** — deploy / update Cloud Run service

```bash
# Deploy odds player‑props scraper
./bin/deploy_run.sh odds-player-props scrapers.oddsapi.oddsa_player_props
```

*Positional args*
`SERVICE` = Cloud Run service name
`MODULE`  = Python module to execute (`python -m …`)

*Environment overrides* `PROJECT`, `REGION`.
The image URI is read from `.last_image`.

---

### **deploy\_workflow\.sh** — deploy / update a Workflow

```bash
./bin/deploy_workflow.sh odds_ingest workflows/odds_ingest.yaml
```

`NAME` = workflow name  `FILE` = path to YAML
Env `PROJECT`, `REGION` override defaults.

---

## 2  Common Cloud Run / Workflow commands

```bash
# List Cloud Run services
gcloud run services list --region us-west2

# List revisions of one service
gcloud run revisions list --service odds-player-props --region us-west2

# Tail last 20 log lines
gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="odds-player-props"' \
  --limit 20 --freshness 1h --project $PROJECT

# List workflows
gcloud workflows list --location us-west2

# List recent executions of a workflow
gcloud workflows executions list odds_ingest_workflow --location us-west2 --limit 5
```

---

## 3  Terraform basics (infra/ directory)

```bash
# Preview changes
cd infra && terraform plan

# Apply updated image tag or config
terraform apply -auto-approve
```

*(Add `lifecycle { ignore_changes = [ template[0].containers[0].image ] }`
to your Cloud Run resource if you prefer to deploy images with `gcloud run`
and let Terraform ignore tag drift.)*

---

## 4  Three‑step dev loop

```bash
# 1. Build & push new image
./bin/build_image.sh $(git rev-parse --short HEAD)

# 2. Deploy / update Cloud Run service
./bin/deploy_run.sh odds-player-props scrapers.oddsapi.oddsa_player_props

# 3. Trigger workflow & verify
gcloud workflows run odds_ingest_workflow --location us-west2
```

---

## 5  Console quick links

* **Cloud Run › Services** → logs & metrics per service
* **Workflows › Executions** → step‑level status & errors
* **BigQuery › ops.scraper\_runs** → STARTED / SUCCESS / FAILED rows

Memorise the three‑step loop, keep this guide handy for everything else, and you’re set. 🌴🚀

```
