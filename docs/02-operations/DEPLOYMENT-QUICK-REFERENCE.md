# Deployment Quick Reference Card

**Keep this handy for quick deployments**

---

## Prerequisites Check

```bash
gcloud auth list                              # Check authentication
gcloud config get-value project               # Verify project (should be nba-props-platform)
gcloud run services list --region=us-west2    # Verify access
```

---

## Quick Deploy Commands

### Analytics Processor (Phase 3)
```bash
cd /home/naji/code/nba-stats-scraper
./scripts/deploy/deploy-analytics.sh
```

### Prediction Coordinator (Phase 5)
```bash
cd /home/naji/code/nba-stats-scraper
./scripts/deploy/deploy-predictions.sh prod    # or 'dev'
```

### Full Deployments (with tests)
```bash
./bin/analytics/deploy/deploy_analytics_processors.sh
./bin/predictions/deploy/deploy_prediction_coordinator.sh prod
```

---

## Verify Deployment

```bash
# Check service status (look for green ✔ not yellow !)
gcloud run services list --region=us-west2 | grep SERVICE_NAME

# Get service URL
SERVICE_URL=$(gcloud run services describe SERVICE_NAME --region=us-west2 --format="value(status.url)")

# Test health (analytics requires auth)
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$SERVICE_URL/health"

# Test health (predictions allows public)
curl "$SERVICE_URL/health"

# Check logs
gcloud run services logs read SERVICE_NAME --region=us-west2 --limit=50
```

---

## Rollback

```bash
# List revisions
gcloud run revisions list --service=SERVICE_NAME --region=us-west2 --limit=5

# Rollback to previous
gcloud run services update-traffic SERVICE_NAME \
  --to-revisions=PREVIOUS_REVISION_NAME=100 \
  --region=us-west2
```

---

## Common Issues

| Issue | Quick Fix |
|-------|-----------|
| "Image not found" | Use `--source=.` not `--image=gcr.io/...` |
| Build hangs | Check `gcloud builds list --limit=5` |
| Yellow warning (!) | Check logs: `gcloud run services logs read SERVICE_NAME --region=us-west2 --limit=100` |
| Permission denied | Verify project: `gcloud config get-value project` |
| 404 on endpoints | Check if service started in logs |
| Import errors | Check Dockerfile COPY commands include all needed files |

---

## Service Configuration

| Service | Memory | CPU | Timeout | Concurrency |
|---------|--------|-----|---------|-------------|
| analytics-processors | 8Gi | 4 | 3600s | 1 |
| precompute-processors | 8Gi | 4 | 3600s | 1 |
| prediction-coordinator | 2Gi | 2 | 1800s | 8 |
| raw-processors | 4Gi | 2 | 3600s | 1 |
| scrapers | 2Gi | 2 | 540s | 1 |

---

## Service Endpoints

### Analytics Processor
```bash
SERVICE_URL="https://nba-phase3-analytics-processors-756957797294.us-west2.run.app"

# Health
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$SERVICE_URL/health"

# Process
curl -X POST "$SERVICE_URL/process-analytics" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"processor": "player_game_summary", "start_date": "2026-01-27", "end_date": "2026-01-27"}'
```

### Prediction Coordinator
```bash
SERVICE_URL="https://prediction-coordinator-756957797294.us-west2.run.app"

# Health
curl "$SERVICE_URL/health"

# Start batch
curl -X POST "$SERVICE_URL/start" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-01-27"}'
```

---

## Emergency Rollback Script

```bash
#!/bin/bash
SERVICE_NAME="$1"
REVISIONS=$(gcloud run revisions list --service=$SERVICE_NAME --region=us-west2 --limit=2 --format="value(metadata.name)" --sort-by="~metadata.creationTimestamp")
PREVIOUS=$(echo "$REVISIONS" | tail -n1)
gcloud run services update-traffic $SERVICE_NAME --to-revisions=$PREVIOUS=100 --region=us-west2
```

---

## Key Reminders

1. **Always deploy from project root:** `/home/naji/code/nba-stats-scraper`
2. **Use Artifact Registry, not Container Registry:** `us-west2-docker.pkg.dev` not `gcr.io`
3. **Source deploy is preferred:** `--source=.` (simpler, automatic)
4. **Check project first:** Should be `nba-props-platform`
5. **Green checkmark = healthy:** Yellow ! means investigate
6. **Test before celebrating:** Run health check and verify logs

---

## Documentation

- **Full Runbook:** [DEPLOYMENT.md](./DEPLOYMENT.md)
- **Troubleshooting:** [DEPLOYMENT-TROUBLESHOOTING.md](./DEPLOYMENT-TROUBLESHOOTING.md)
- **Scripts:** [/scripts/deploy/](../../scripts/deploy/)

---

## Support

1. Check this reference
2. Check [DEPLOYMENT-TROUBLESHOOTING.md](./DEPLOYMENT-TROUBLESHOOTING.md)
3. Check service logs
4. Check recent handoffs in [/docs/09-handoff/](../09-handoff/)
5. Ask in #engineering Slack

---

**Print this page and keep it at your desk!**

*Last Updated: 2026-01-27*
