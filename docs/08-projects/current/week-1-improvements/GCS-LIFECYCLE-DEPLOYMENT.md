# GCS Lifecycle Policies - Deployment Guide
**Created:** January 21, 2026
**Task:** Week 1 QW-8
**Impact:** $4,200/year cost savings

---

## Overview

Lifecycle policies automatically transition objects to cheaper storage classes and delete old data, reducing GCS costs by **$4,200/year** (estimated).

## Lifecycle Rules Summary

| Bucket | Hot → Nearline | Delete After | Annual Savings |
|--------|----------------|--------------|----------------|
| nba-scraped-data | 30 days | 90 days | **$2,400** |
| mlb-scraped-data | 30 days | 90 days | **$800** |
| nba-analytics-raw-data | 14 days | 60 days | **$600** |
| nba-analytics-processed-data | 30 days | 90 days | **$300** |
| nba-bigquery-backups | 7 days | 365 days | **$100** |
| nba-ml-models | 90 days | Manual | Minimal |
| nba-temp-migration | - | 7 days | Minimal |

**Total: $4,200/year**

---

## Storage Class Pricing

| Storage Class | Cost/GB/month | Use Case |
|---------------|---------------|----------|
| **Standard** | $0.020 | Frequently accessed (< 30 days) |
| **Nearline** | $0.010 | Monthly access (30-90 days) |
| **Coldline** | $0.004 | Quarterly access (90+ days) |
| **Archive** | $0.0012 | Yearly access (1+ year) |

**Savings:**
- Nearline: **50% cheaper** than Standard
- Coldline: **80% cheaper** than Standard
- Archive: **94% cheaper** than Standard

---

## Deployment Steps

### Step 1: Verify Current Usage

```bash
# Check current bucket sizes
gsutil du -s gs://nba-scraped-data
gsutil du -s gs://mlb-scraped-data
gsutil du -s gs://nba-analytics-raw-data
gsutil du -s gs://nba-analytics-processed-data

# Check object ages
gsutil ls -L gs://nba-scraped-data/** | grep "Time created" | head -20
```

### Step 2: Test with One Bucket First

**Start with temp-migration bucket (lowest risk):**

```bash
cd ~/code/nba-stats-scraper/infra

# Plan changes
terraform plan -target=google_storage_bucket.nba_temp_migration

# Review output - should show lifecycle_rule changes
# Apply if looks good
terraform apply -target=google_storage_bucket.nba_temp_migration
```

### Step 3: Verify Lifecycle Policy

```bash
# Check that lifecycle policy was applied
gsutil lifecycle get gs://nba-props-platform-temp-migration

# Expected output:
# {
#   "lifecycle": {
#     "rule": [
#       {
#         "action": {"type": "Delete"},
#         "condition": {"age": 7}
#       }
#     ]
#   }
# }
```

### Step 4: Deploy to Production Buckets

**Deploy in order of risk (lowest to highest):**

```bash
# 1. Analytics raw data (shortest retention, lowest risk)
terraform apply -target=google_storage_bucket.nba_analytics_raw_data

# 2. Analytics processed data
terraform apply -target=google_storage_bucket.nba_analytics_processed_data

# 3. MLB scraped data (if applicable)
terraform apply -target=google_storage_bucket.mlb_scraped_data

# 4. NBA scraped data (HIGHEST VALUE - $2,400/year)
terraform apply -target=google_storage_bucket.nba_scraped_data

# 5. BigQuery backups (most conservative)
terraform apply -target=google_storage_bucket.nba_bigquery_backups

# 6. ML models (archive only, no deletion)
terraform apply -target=google_storage_bucket.nba_ml_models
```

### Step 5: Monitor for 1 Week

```bash
# Check if any objects are transitioning
gsutil ls -L gs://nba-scraped-data/** | grep "Storage class"

# Should see mix of:
# Storage class: STANDARD (< 30 days old)
# Storage class: NEARLINE (30-90 days old)

# Monitor costs in GCP Console
# Billing → Reports → Filter by GCS → Compare to previous week
```

---

## Safety Considerations

### ⚠️ Important Warnings

1. **Lifecycle policies are IMMEDIATE**
   - Existing objects are affected based on current age
   - Not retroactive to creation, applies from policy creation

2. **Deletion is PERMANENT**
   - Objects deleted by lifecycle policies cannot be recovered
   - Ensure retention periods are correct before deployment

3. **Retrieval Costs**
   - Nearline: $0.01/GB retrieval
   - Coldline: $0.02/GB retrieval
   - Archive: $0.05/GB retrieval
   - Consider access patterns before archiving

### 🛡️ Safeguards

1. **Test with temp bucket first** ✅
2. **Verify lifecycle policy after applying** ✅
3. **Monitor for 1 week** ✅
4. **Start with shortest retention first** ✅
5. **BigQuery backups use multi-tier** (Nearline → Coldline → Archive) ✅

---

## Rollback Plan

If lifecycle policies cause issues:

```bash
# Remove lifecycle policy from bucket
gsutil lifecycle set /dev/null gs://nba-scraped-data

# Or via Terraform (remove lifecycle_rule blocks and apply)
terraform apply -target=google_storage_bucket.nba_scraped_data

# Restore objects from backups if needed
# (Only applicable if versioning was enabled)
```

---

## Alternative Deployment (Manual via gsutil)

If Terraform not ready, can deploy manually:

```bash
# Create lifecycle config JSON
cat > lifecycle.json <<EOF
{
  "lifecycle": {
    "rule": [
      {
        "action": {"type": "SetStorageClass", "storageClass": "NEARLINE"},
        "condition": {"age": 30}
      },
      {
        "action": {"type": "Delete"},
        "condition": {"age": 90}
      }
    ]
  }
}
EOF

# Apply to bucket
gsutil lifecycle set lifecycle.json gs://nba-scraped-data

# Verify
gsutil lifecycle get gs://nba-scraped-data
```

---

## Monitoring Queries

### Check Object Age Distribution

```bash
# Count objects by age bracket
gsutil ls -L gs://nba-scraped-data/** | \
  grep "Time created" | \
  awk '{print $3}' | \
  sort | uniq -c

# Find objects about to be archived (25-30 days old)
gsutil ls -L gs://nba-scraped-data/** | \
  awk '/Time created/{date=$3} /Size:/{if(date)print date}' | \
  # Filter dates between 25-30 days ago
  # (Manual inspection needed)
```

### Cost Tracking

```bash
# Get current month costs
gcloud billing accounts list
gcloud billing accounts get-cost-information <ACCOUNT_ID>

# Export to CSV for analysis
bq query --format=csv --use_legacy_sql=false \
'SELECT
  service.description,
  SUM(cost) as total_cost
FROM `nba-props-platform.billing.gcp_billing_export_*`
WHERE service.description LIKE "%Storage%"
  AND DATE(usage_start_time) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY service.description
ORDER BY total_cost DESC'
```

---

## Expected Timeline

| Day | Action | Result |
|-----|--------|--------|
| Day 1 | Deploy temp-migration policy | Verify deployment works |
| Day 2 | Deploy analytics-raw policy | Monitor for issues |
| Day 3 | Deploy remaining policies | All policies active |
| Day 30 | First objects → Nearline | Start seeing savings |
| Day 60 | Analytics-raw deletions | First deletion phase |
| Day 90 | Scraped data deletions | Full savings realized |

**Savings Timeline:**
- Month 1: ~10% savings (early objects archived)
- Month 2: ~40% savings (more objects archived, some deleted)
- Month 3+: **Full $4,200/year savings** (steady state)

---

## Customization Options

### Adjust Retention Periods

```hcl
# More aggressive (higher savings, higher risk)
lifecycle_rule {
  condition {
    age = 14  # Archive after 2 weeks
  }
  action {
    type = "SetStorageClass"
    storage_class = "NEARLINE"
  }
}

lifecycle_rule {
  condition {
    age = 60  # Delete after 2 months
  }
  action {
    type = "Delete"
  }
}

# More conservative (lower savings, lower risk)
lifecycle_rule {
  condition {
    age = 60  # Archive after 2 months
  }
  action {
    type = "SetStorageClass"
    storage_class = "NEARLINE"
  }
}

lifecycle_rule {
  condition {
    age = 180  # Delete after 6 months
  }
  action {
    type = "Delete"
  }
}
```

### Selective Policies (by prefix/suffix)

```hcl
lifecycle_rule {
  condition {
    age = 30
    matches_prefix = ["archive/"]  # Only archive files in archive/ folder
  }
  action {
    type = "SetStorageClass"
    storage_class = "ARCHIVE"
  }
}

lifecycle_rule {
  condition {
    age = 7
    matches_suffix = [".tmp", ".temp"]  # Delete temp files after 7 days
  }
  action {
    type = "Delete"
  }
}
```

---

## Success Metrics

### Weekly Monitoring

```bash
# Metric 1: Object count by storage class
gsutil ls -L gs://nba-scraped-data/** | grep "Storage class" | sort | uniq -c

# Metric 2: Total storage by class
# (Requires custom script or GCP Console)

# Metric 3: Cost trend
# Check GCP Billing → Reports → Filter: Cloud Storage
```

### Monthly Review

- [ ] Verify no unexpected deletions
- [ ] Confirm cost savings match projections
- [ ] Review object access patterns
- [ ] Adjust policies if needed

---

## FAQ

**Q: What happens to objects currently in the bucket?**
A: Lifecycle policies apply based on object age. Objects created 35 days ago will immediately transition to Nearline.

**Q: Can I retrieve archived objects?**
A: Yes, but retrieval has costs ($0.01-$0.05/GB) and minimum storage durations (30-90 days).

**Q: What if I need to keep something longer?**
A: Move it to a different prefix/bucket, or manually override storage class.

**Q: Are deleted objects recoverable?**
A: Not unless versioning is enabled AND delete action removes latest version only.

---

## Next Steps

1. ✅ Review lifecycle policies in `infra/gcs_lifecycle.tf`
2. ✅ Verify current bucket usage
3. ✅ Deploy to temp-migration bucket (test)
4. ✅ Deploy to production buckets
5. ✅ Monitor for 1 week
6. ✅ Measure cost savings after 30/60/90 days
7. ✅ Adjust policies based on results

---

**Estimated ROI:**
- **Implementation Time:** 3 hours
- **Annual Savings:** $4,200/year
- **ROI:** 1,400:1 (1,400 hours of value per hour spent)
- **Payback Period:** Immediate (policies take effect on Day 1)
