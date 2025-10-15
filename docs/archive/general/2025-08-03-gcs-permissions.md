# NBA Props Platform - GCS Permissions & Service Account Guide

**Document Version:** 1.0  
**Date:** August 3, 2025  
**Context:** Backfill workflow development and GCS permissions troubleshooting

## Overview

This document captures the permissions architecture, issues encountered, and solutions implemented during the NBA backfill workflow development. It serves as a reference for understanding how different components of the NBA Props Platform interact with Google Cloud Storage and what permissions are required.

## Architecture Summary

### Service Accounts in Use

**Primary Service Account:**
- **Name:** `756957797294-compute@developer.gserviceaccount.com`
- **Type:** Default Compute Engine service account
- **Used By:** Both Cloud Run services AND Workflows

### Storage Buckets

| Bucket Name | Purpose | Primary Writers | Folder Structure |
|-------------|---------|-----------------|------------------|
| `nba-scraped-data` | Raw scraped data storage | Cloud Run services | `nba-com/`, `big-data-ball/` |
| `nba-props-status` | Workflow execution status | Workflows | `workflow-status/` |

## The Permission Problem We Encountered

### Issue Description
During backfill workflow development, we encountered a puzzling scenario:
- ✅ **Cloud Run → `nba-scraped-data`** worked perfectly
- ❌ **Workflows → `nba-props-status`** consistently failed

### Why This Was Confusing
Both services used the **same service account** (`756957797294-compute@developer.gserviceaccount.com`), yet one could write to GCS while the other couldn't.

## Root Cause Analysis

### Initial Assumptions (Wrong)
1. **Different service accounts** - We thought Cloud Run and Workflows might use different accounts
2. **Different bucket permissions** - We thought the buckets had different IAM policies
3. **Missing project-level roles** - We thought the service account lacked storage permissions

### Actual Root Causes (Correct)

#### 1. **Explicit vs. Inherited Permissions**
```bash
# Service account had project-level editor role
roles/editor  # Should include storage permissions

# But buckets only had project-level bindings
projectEditor:nba-props-platform
projectOwner:nba-props-platform

# Missing explicit service account binding
```

#### 2. **API Endpoint Differences**
- **Cloud Run services** used internal GCS libraries with proper authentication
- **Workflows** used manual HTTP API calls with token management issues

#### 3. **Permission Inheritance Complexity**
Project-level `roles/editor` should theoretically grant storage access, but GCS bucket-level policies can override or restrict these permissions.

## Diagnostic Steps We Used

### 1. Service Account Discovery
```bash
# Check what service account workflows use
gcloud workflows describe collect-nba-historical-schedules --location=us-west2 --format="value(serviceAccount)"

# Check what service account Cloud Run uses  
gcloud run services describe nba-scrapers --region=us-west2 --format="value(spec.template.spec.serviceAccountName)"
```

### 2. Permission Audit
```bash
# Check project-level permissions
gcloud projects get-iam-policy nba-props-platform --flatten="bindings[].members" --filter="bindings.members:$SERVICE_ACCOUNT"

# Check bucket-level permissions
gcloud storage buckets get-iam-policy gs://bucket-name --format="table(bindings.role,bindings.members)"
```

### 3. Permission Testing
```bash
# Manual test to verify service account can write
echo '{"test": "data"}' | gcloud storage cp - gs://nba-props-status/workflow-status/test.json
```

### 4. Log Analysis
```bash
# Check workflow logs for GCS errors
gcloud logging read 'resource.type="workflows.googleapis.com/Workflow"' --limit=20
```

## Solutions Implemented

### 1. **Explicit Bucket Permissions**
```bash
# Added explicit service account permission to bucket
gcloud storage buckets add-iam-policy-binding gs://nba-props-status \
  --member="serviceAccount:756957797294-compute@developer.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
```

**Result:** Service account now had explicit bucket-level access, not just inherited project-level access.

### 2. **Native GCS Connector in Workflows**
**Old approach (Failed):**
```yaml
call: http.post
args:
  url: ${"https://storage.googleapis.com/upload/storage/v1/b/" + bucket_name + "/o"}
  headers:
    Authorization: ${"Bearer " + sys.get_env("GOOGLE_CLOUD_ACCESS_TOKEN")}
```

**New approach (Success):**
```yaml
call: googleapis.storage.v1.objects.insert
args:
  bucket: ${bucket_name}
  name: ${file_path}
  uploadType: "media"
  body: ${json.encode(status_data)}
```

**Why this worked:**
- Automatic authentication handling
- Correct API format and headers
- No manual token management required

## Current Permission Architecture

### Project-Level IAM
```
Service Account: 756957797294-compute@developer.gserviceaccount.com
Roles:
  - roles/editor                    # Broad project permissions
  - roles/logging.logWriter         # Write to Cloud Logging  
  - roles/monitoring.metricWriter   # Write metrics
  - roles/workflows.invoker         # Invoke workflows
```

### Bucket-Level IAM

#### `nba-scraped-data` bucket
```
Project-level bindings:
  - projectEditor:nba-props-platform
  - projectOwner:nba-props-platform
  
Note: Cloud Run services write successfully through project-level inheritance
```

#### `nba-props-status` bucket  
```
Project-level bindings:
  - projectEditor:nba-props-platform
  - projectOwner:nba-props-platform

Explicit service account binding:
  - serviceAccount:756957797294-compute@developer.gserviceaccount.com
    Role: roles/storage.objectAdmin
```

## Data Flow & Permission Usage

### 1. **Operational Workflows → Cloud Run → GCS**
```
Workflow (Service Account) → HTTP → Cloud Run (Service Account) → GCS Write
```
- **Workflow permissions:** HTTP client capabilities
- **Cloud Run permissions:** Storage write via project-level inheritance
- **Writes to:** `gs://nba-scraped-data/nba-com/schedule/`

### 2. **Operational Workflows → Direct GCS Write**
```
Workflow (Service Account) → Direct GCS API → GCS Write
```
- **Workflow permissions:** Explicit bucket-level `storage.objectAdmin`
- **Writes to:** `gs://nba-props-status/workflow-status/`

### 3. **Backfill Workflow (Combined Pattern)**
```
Workflow → Cloud Run → nba-scraped-data (schedule data)
Workflow → Direct GCS → nba-props-status (status tracking)
```

## Lessons Learned

### 1. **Explicit > Inherited Permissions**
Even when service accounts have broad project-level roles like `roles/editor`, explicitly granting bucket-level permissions is more reliable and clearer.

### 2. **Native Connectors > Manual HTTP APIs**
Google Cloud Workflows provides native connectors (like `googleapis.storage.v1.objects.insert`) that handle authentication automatically and are more reliable than manual HTTP API calls.

### 3. **Different Services, Different Patterns**
- **Cloud Run services:** Work well with project-level inherited permissions
- **Workflows:** Often need explicit bucket-level permissions for direct GCS access

### 4. **Debugging Strategy**
1. ✅ **Verify service accounts** - Ensure you know which account each service uses
2. ✅ **Test permissions manually** - Use `gcloud storage cp` to verify access
3. ✅ **Check logs thoroughly** - Look for specific error messages
4. ✅ **Prefer explicit permissions** - Don't rely on inheritance for critical operations

## Best Practices Going Forward

### 1. **Permission Strategy**
- Use **explicit bucket-level permissions** for Workflows that write directly to GCS
- Rely on **project-level permissions** for Cloud Run services (they work fine)
- Document which service accounts are used by which components

### 2. **Workflow GCS Integration**
- Prefer **native GCS connectors** over HTTP APIs in workflows
- Always include proper error handling and logging for GCS operations
- Test GCS writes during workflow development, not just at the end

### 3. **Bucket Organization**
- Keep **data buckets** (`nba-scraped-data`) separate from **status buckets** (`nba-props-status`)
- Use consistent folder structures (`workflow-status/`, `nba-com/schedule/`)
- Consider bucket-level lifecycle policies for old status files

### 4. **Monitoring & Debugging**
- Include status writing in all production workflows
- Log GCS operations with clear success/failure messages
- Use execution IDs to correlate workflow runs with status files

## Troubleshooting Guide

### Symptoms: "Failed to write status to GCS"

**Step 1:** Check service account
```bash
gcloud workflows describe WORKFLOW_NAME --location=REGION --format="value(serviceAccount)"
```

**Step 2:** Verify bucket permissions
```bash
gcloud storage buckets get-iam-policy gs://BUCKET_NAME --format="json" | grep SERVICE_ACCOUNT
```

**Step 3:** Test manual write
```bash
echo '{"test": "data"}' | gcloud storage cp - gs://BUCKET_NAME/test-path/test.json
```

**Step 4:** Check workflow logs
```bash
gcloud logging read 'resource.type="workflows.googleapis.com/Workflow"' --limit=10
```

**Step 5:** Add explicit permission if needed
```bash
gcloud storage buckets add-iam-policy-binding gs://BUCKET_NAME \
  --member="serviceAccount:SERVICE_ACCOUNT_EMAIL" \
  --role="roles/storage.objectAdmin"
```

### Symptoms: Cloud Run can't write to GCS

**Usually caused by:**
- Missing project-level `roles/editor` or `roles/storage.admin`
- Cloud Run service using wrong service account

**Solution:**
```bash
# Add storage permissions to Cloud Run service account
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:SERVICE_ACCOUNT_EMAIL" \
  --role="roles/storage.admin"
```

## Security Considerations

### Principle of Least Privilege
- **Workflows:** Only need `storage.objectAdmin` on specific buckets they write to
- **Cloud Run:** Can use broader `roles/editor` since they need multiple service integrations
- **Buckets:** Consider private access with explicit service account bindings

### Service Account Hygiene
- Use the **default compute service account** for simplicity in development
- Consider **custom service accounts** with minimal permissions for production
- Regularly audit permissions with `gcloud projects get-iam-policy`

## Future Considerations

### 1. **Custom Service Accounts**
As the system grows, consider creating specific service accounts:
- `nba-workflows@PROJECT.iam.gserviceaccount.com` - For workflow execution
- `nba-scrapers@PROJECT.iam.gserviceaccount.com` - For Cloud Run services

### 2. **Cross-Project Permissions**
If expanding to multiple projects, document cross-project service account usage and bucket access patterns.

### 3. **Bucket Lifecycle Management**
Implement lifecycle policies for status files (e.g., delete after 90 days) to manage storage costs.

---

**Document Owner:** Development Team  
**Last Updated:** August 3, 2025  
**Next Review:** During next major system expansion
