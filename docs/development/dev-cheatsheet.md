# Dev Cheat‑Sheet – Scrapers • Cloud Run • Workflows

## 1. Build image
make build-image TAG=2025-07-11

## 2. Deploy odds player‑props scraper
make deploy-odds

## 3. Deploy / run workflow
make deploy-workflow
make run-workflow

## 4. Query BigQuery
bq query --use_legacy_sql=false \
'SELECT * FROM `$(PROJECT).ops.scraper_runs` ORDER BY run_ts DESC LIMIT 20'
