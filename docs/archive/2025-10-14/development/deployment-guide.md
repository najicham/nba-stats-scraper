# Deployment Guide

How to deploy changes to the NBA Props Platform.

**Last Updated:** $(date +%Y-%m-%d)

## Quick Deploy

### Scrapers
```bash
./bin/scrapers/deploy/deploy_scrapers_simple.sh
```

### Processors
```bash
./bin/processors/deploy/deploy_processors_simple.sh
```

### Analytics
```bash
./bin/analytics/deploy/deploy_analytics_processors.sh
```

### Workflows
```bash
./bin/infrastructure/workflows/deploy_workflows.sh
```

## Deployment Process

1. **Test locally first**
2. **Deploy to Cloud Run**
3. **Verify deployment**
4. **Monitor for errors**

## Rollback

If something goes wrong:

```bash
# List revisions
gcloud run revisions list --service=nba-scrapers --region=us-west2

# Rollback to previous
gcloud run services update-traffic nba-scrapers \
  --region=us-west2 \
  --to-revisions=nba-scrapers-00057-xyz=100
```

## Best Practices

- Deploy during low-traffic times
- Test with small date ranges first
- Monitor logs after deployment
- Keep deployment scripts up to date

## Related

- [cloud-run-deployment.md](cloud-run-deployment.md) - Cloud Run specifics
- [development-workflow.md](development-workflow.md) - Full development process
