# Deployment Scripts AWS SES Migration Status

## Summary

Updated all NBA deployment scripts to use AWS SES (primary) with Brevo fallback.

**Key Change:** Credentials are retrieved from GCP Secret Manager instead of being passed as environment variables.

## Completed Updates

### High Priority (Production Services) ✅ DONE

1. **`bin/scrapers/deploy/deploy_scrapers_simple.sh`**
   - Status: ✅ Updated
   - Uses: AWS SES (primary), Brevo (fallback)
   - Credentials: From Secret Manager

2. **`bin/raw/deploy/deploy_processors_simple.sh`**
   - Status: ✅ Updated
   - Uses: AWS SES (primary), Brevo (fallback)
   - Credentials: Mounted via `--set-secrets` (best practice!)
   - Note: This script was already using Cloud Run secret mounting

3. **`bin/precompute/deploy/deploy_precompute_processors.sh`**
   - Status: ✅ Updated
   - Uses: AWS SES (primary), Brevo (fallback)
   - Credentials: From Secret Manager

4. **`bin/reference/deploy/deploy_reference_processors.sh`**
   - Status: ✅ Updated
   - Uses: AWS SES (primary), Brevo (fallback)
   - Credentials: From Secret Manager

5. **`bin/analytics/deploy/deploy_analytics_processors.sh`**
   - Status: ✅ Updated (earlier)
   - Uses: AWS SES (primary), Brevo (fallback)
   - Credentials: From Secret Manager

6. **`bin/shared/deploy_common.sh`**
   - Status: ✅ Updated
   - Shared functions now support AWS SES
   - Affects any script using `add_email_config_to_env_vars()`

### Medium Priority (MLB Services) ⏸️ DEFERRED

7. **`bin/analytics/deploy/mlb/deploy_mlb_analytics.sh`**
   - Status: ⏸️ Needs update
   - Current: Brevo only
   - Note: Lower priority - MLB season not active

8. **`bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh`**
   - Status: ⏸️ Needs update
   - Current: Brevo only

9. **`bin/precompute/deploy/mlb/deploy_mlb_precompute.sh`**
   - Status: ⏸️ Needs update
   - Current: Brevo only

10. **`bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh`**
    - Status: ⏸️ Needs update
    - Current: Brevo only

11. **`bin/phase6/deploy/mlb/deploy_mlb_grading.sh`**
    - Status: ⏸️ Needs update
    - Current: Brevo only

### Low Priority ⏸️ DEFERRED

12. **`bin/monitoring/deploy/deploy_freshness_monitor.sh`**
    - Status: ⏸️ Needs update
    - Current: Brevo only
    - Note: Monitoring service, rarely redeployed

13. **`bin/scrapers/deploy/deploy_scrapers_backfill_job.sh`**
    - Status: ⏸️ Needs update
    - Current: Brevo only
    - Note: Backfill job, one-time use

## What's Working Now

### Production NBA Services
All critical production NBA services now support AWS SES:
- ✅ Scrapers (Phase 1)
- ✅ Raw Processors (Phase 2)
- ✅ Analytics Processors (Phase 3)
- ✅ Precompute Processors (Phase 4)
- ✅ Reference Processors

### How It Works

1. **Credentials in Secret Manager** (secure)
   ```
   aws-ses-access-key-id
   aws-ses-secret-access-key
   brevo-smtp-password
   ```

2. **Configuration in .env** (not secrets)
   ```bash
   AWS_SES_REGION=us-west-2
   AWS_SES_FROM_EMAIL=alert@989.ninja
   EMAIL_ALERTS_TO=your-email@example.com
   ```

3. **Automatic Fallback**
   ```
   Try AWS SES (Secret Manager)
     ↓ (if fails)
   Try Brevo (Secret Manager)
     ↓ (if fails)
   No email alerts
   ```

## Deployment Verification

After deploying any service, verify it's using AWS SES:

```bash
# Check deployment status
gcloud run services describe SERVICE_NAME --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env)"

# Look for in deployment output:
# "Email alerting: AWS SES (primary), Brevo (fallback)"

# Check logs after first alert:
# "Using AWS SES credentials from Secret Manager"
```

## Deferred Scripts

The 7 deferred scripts (MLB services + monitoring) will continue using Brevo until updated. They can be batch-updated later since:
- MLB season not currently active
- Lower priority than NBA production services
- Will automatically fall back to Brevo (still works)

### Quick Batch Update (Future)

When ready to update MLB scripts:

```bash
# Pattern to replace in each script:
# OLD: if [[ -n "$BREVO_SMTP_PASSWORD" && -n "$EMAIL_ALERTS_TO" ]]
# NEW: if [[ -n "$EMAIL_ALERTS_TO" ]]

# OLD: Brevo config only
# NEW: AWS SES + Brevo config (like updated scripts)
```

## Testing

### Test AWS SES is Working

1. Deploy a service:
   ```bash
   ./bin/analytics/deploy/deploy_analytics_processors.sh
   ```

2. Check deployment output shows:
   ```
   ✅ Adding email alerting configuration...
      Email alerting: AWS SES (primary), Brevo (fallback)
   ```

3. Trigger an alert (or wait for scheduled run)

4. Verify email:
   - From: `alert@989.ninja`
   - Headers include: `X-SES-Message-ID`
   - No Brevo headers

5. Check application logs:
   ```bash
   gcloud run services logs read nba-phase3-analytics-processors \
     --region=us-west2 \
     --limit=50 | grep -i "ses\|email"
   ```

   Should see:
   ```
   Using AWS SES credentials from Secret Manager
   ```

## Rollback Plan

If AWS SES has issues:

1. **Automatic Fallback**: System will automatically use Brevo if AWS SES fails
2. **No Action Needed**: Brevo credentials also in Secret Manager
3. **Manual Override**: Set env var to force Brevo (not recommended)

## Benefits Achieved

### Security
- ✅ Credentials in Secret Manager (not .env)
- ✅ Automatic credential rotation support
- ✅ IAM-based access control
- ✅ Audit logs for credential access

### Cost
- ✅ AWS SES: $0.10 per 1,000 emails
- ✅ Brevo: $25/month minimum
- ✅ Estimated savings: $20-25/month

### Reliability
- ✅ Automatic fallback to Brevo
- ✅ Better deliverability with AWS SES
- ✅ Higher rate limits

## Next Steps

### Immediate
- [x] Clean up .env file (remove secrets)
- [x] Deploy updated services
- [ ] Verify AWS SES email alerts working
- [ ] Monitor for 1 week

### Future (When Convenient)
- [ ] Update remaining 7 deployment scripts (MLB + monitoring)
- [ ] Remove Brevo entirely once AWS SES confirmed stable (optional)
- [ ] Document credential rotation procedure

## Files Modified

### Code
- `bin/shared/deploy_common.sh` - Shared deployment utilities
- `bin/scrapers/deploy/deploy_scrapers_simple.sh` - NBA scrapers
- `bin/raw/deploy/deploy_processors_simple.sh` - Raw processors
- `bin/precompute/deploy/deploy_precompute_processors.sh` - Precompute
- `bin/reference/deploy/deploy_reference_processors.sh` - Reference
- `bin/analytics/deploy/deploy_analytics_processors.sh` - Analytics
- `shared/utils/email_alerting_ses.py` - AWS SES email handler

### Documentation
- `.env.example` - Updated with Secret Manager guidance
- `docs/08-projects/current/week-1-improvements/AWS-SES-MIGRATION.md`
- `docs/08-projects/current/week-1-improvements/SECRET-MANAGEMENT-REFERENCE.md`
- `docs/08-projects/current/week-1-improvements/DEPLOYMENT-SCRIPTS-AWS-SES-STATUS.md` (this file)

## Summary Status

| Category | Total | Updated | Deferred | Status |
|----------|-------|---------|----------|--------|
| High Priority (NBA Production) | 6 | 6 | 0 | ✅ 100% Complete |
| Medium Priority (MLB Services) | 5 | 0 | 5 | ⏸️ Deferred |
| Low Priority (Misc) | 2 | 0 | 2 | ⏸️ Deferred |
| **Total** | **13** | **6** | **7** | **46% Complete** |

**Production NBA Services: ✅ 100% Complete**

All critical production NBA services now use AWS SES with Brevo fallback!
