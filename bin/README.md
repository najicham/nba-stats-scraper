# NBA Scrapers DevOps Guide
*Simple unified architecture for NBA stats scraping*

---

## 1. Quick Commands

```bash
# Deploy scrapers to Cloud Run
make deploy

# Test the deployment
make test

# View recent logs
make logs

# Deploy and test in one command
make deploy-test
```

---

## 2. Helper Scripts in `bin/`

### **deploy_scrapers.sh** — Deploy unified scraper service
```bash
./bin/deploy_scrapers.sh
```

Deploys the unified NBA scrapers service to Cloud Run using source-based deployment.

*Requirements*:
- `ODDS_API_KEY` environment variable must be set
- Authenticated with gcloud (`gcloud auth login`)

---

### **test_scrapers.sh** — Test the deployed service
```bash
./bin/test_scrapers.sh
```

Runs comprehensive tests:
- Health check
- Available scrapers list
- Odds API historical events test
- GCS bucket verification

---

### **logs_scrapers.sh** — View recent logs
```bash
./bin/logs_scrapers.sh
```

Shows the last 20 log entries from the NBA scrapers service.

---

### **deploy_workflow.sh** — Deploy Workflows (unchanged)
```bash
./bin/deploy_workflow.sh workflow_name path/to/workflow.yaml
```

Still used for deploying Google Cloud Workflows when needed.

---

## 3. Development Workflow

### Simple 2-step loop:
```bash
# 1. Deploy your changes
make deploy

# 2. Test they work
make test
```

### Debug if needed:
```bash
# Check logs
make logs

# Check service status
gcloud run services describe nba-scrapers --region us-west2
```

---

## 4. Architecture Overview

**Unified Service**: Single Cloud Run service (`nba-scrapers`) handles all scraper types
**Routing**: POST to `/scrape` with `{"scraper": "oddsa_events_his", ...}`
**Available Scrapers**: GET `/scrapers` to see all available scrapers

### Example API calls:
```bash
# List available scrapers
curl https://nba-scrapers-[hash].a.run.app/scrapers

# Run odds historical events scraper
curl -X POST https://nba-scrapers-[hash].a.run.app/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "scraper": "oddsa_events_his",
    "sport": "basketball_nba",
    "date": "2025-07-13T00:00:00Z"
  }'
```

---

## 5. Useful gcloud Commands

```bash
# List Cloud Run services
gcloud run services list --region us-west2

# Get service URL
gcloud run services describe nba-scrapers --region us-west2 --format="value(status.url)"

# View detailed logs
gcloud run services logs read nba-scrapers --region us-west2 --limit 50

# Check recent GCS files
gsutil ls gs://nba-analytics-raw-data/oddsapi/historical-events/ | tail -10
```

---

## 6. Troubleshooting

### Common Issues:

**Deployment fails**:
- Check `ODDS_API_KEY` is set: `echo $ODDS_API_KEY`
- Verify gcloud auth: `gcloud auth list`

**Service returns errors**:
- Check logs: `make logs`
- Test health endpoint: `curl $SERVICE_URL/health`

**No data in GCS**:
- Normal for empty snapshots (204 responses)
- Check logs for any error messages

---

## 7. Archived Scripts

Previous multi-service architecture scripts are preserved in `bin/archive/`:
- `build_image.sh` - Container building
- `deploy_all_services.sh` - Multi-service deployment  
- `deploy_cloud_run.sh` - Complex deployment
- `deploy_run.sh` - Individual service deployment

These can be referenced if returning to a multi-service architecture later.

---

## 8. Future Growth

**Phase 1** (current): Simple unified service  
**Phase 2**: Add more scrapers to the unified service  
**Phase 3**: Add automation (Cloud Scheduler, monitoring)  
**Phase 4**: Add sophistication (Cloud Build, Terraform, multiple environments)

Keep it simple until you need the complexity! 🚀
