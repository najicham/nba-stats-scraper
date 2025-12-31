# 🚨 CRITICAL SECURITY AUDIT - 2025-12-31

## Executive Summary

**CRITICAL VULNERABILITIES FOUND:** Multiple production services are publicly accessible without authentication.

**Severity:** P0 - CRITICAL
**Impact:** High - Anyone can trigger expensive operations, DoS attacks, data manipulation
**Remediation Time:** 15-30 minutes
**Action Required:** IMMEDIATE

---

## Vulnerability Summary

| Service | Status | IAM Policy | HTTP Test | Risk Level |
|---------|--------|------------|-----------|------------|
| **Phase 1: Scrapers** | ❌ PUBLIC | `allUsers` | 200 OK | HIGH |
| **Phase 2: Raw** | ✅ SECURE | Service accounts only | Not tested | LOW |
| **Phase 3: Analytics** | ✅ SECURE | Service accounts only | 403 Forbidden | LOW |
| **Phase 4: Precompute** | ❌ PUBLIC | `allUsers` + `allAuthenticatedUsers` | 200 OK | CRITICAL |
| **Phase 5: Coordinator** | ❌ PUBLIC | `allUsers` | 200 OK | CRITICAL |
| **Phase 5: Worker** | ❌ PUBLIC | `allUsers` | 200 OK | CRITICAL |
| **Phase 6: Export** | ✅ SECURE | (No explicit policy) | 403 Forbidden | LOW |
| **Admin Dashboard** | ❌ PUBLIC | `allUsers` | 200 OK | CRITICAL |

**Summary:**
- ✅ **Secure:** 3 services (Phase 2, 3, 6)
- ❌ **Vulnerable:** 5 services (Phase 1, 4, 5 coordinator, 5 worker, dashboard)

---

## Detailed Findings

### 🔴 CRITICAL: Phase 4 Precompute (nba-phase4-precompute-processors)

**IAM Policy:**
```yaml
bindings:
- members:
  - allUsers                      # ❌ ANYONE on internet
  - allAuthenticatedUsers         # ❌ Any Google account
  - serviceAccount:scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com
  - serviceAccount:service-756957797294@gcp-sa-pubsub.iam.gserviceaccount.com
  role: roles/run.invoker
```

**Exploit Scenario:**
```bash
# Anyone can trigger expensive BigQuery jobs
curl -X POST https://nba-phase4-precompute-processors-756957797294.us-west2.run.app/process-date \
  -H "Content-Type: application/json" \
  -d '{"analysis_date": "2024-01-01", "processors": []}'
```

**Impact:**
- Trigger expensive BigQuery queries ($$$)
- DoS via repeated requests
- Data corruption via malicious date ranges
- Pipeline disruption

---

### 🔴 CRITICAL: Phase 5 Coordinator (prediction-coordinator)

**IAM Policy:**
```yaml
bindings:
- members:
  - allUsers                      # ❌ ANYONE on internet
  - serviceAccount:scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com
  role: roles/run.invoker
```

**Exploit Scenario:**
```bash
# Anyone can trigger prediction generation
curl -X POST https://prediction-coordinator-756957797294.us-west2.run.app/start \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2024-01-01"}'
```

**Impact:**
- Trigger 450+ worker jobs (expensive)
- Overwrite production predictions
- DoS attack potential
- Resource exhaustion

---

### 🔴 CRITICAL: Phase 5 Worker (prediction-worker)

**IAM Policy:**
```yaml
bindings:
- members:
  - allUsers                      # ❌ ANYONE on internet
  role: roles/run.invoker
```

**Impact:**
- Direct worker manipulation
- Bypass coordinator controls
- Data integrity issues

---

### 🔴 HIGH: Phase 1 Scrapers (nba-phase1-scrapers)

**IAM Policy:**
```yaml
bindings:
- members:
  - allUsers                      # ❌ ANYONE on internet
  role: roles/run.invoker
```

**Impact:**
- Trigger expensive scraping operations
- API quota exhaustion
- Rate limit violations
- Data source bans

---

### 🔴 HIGH: Admin Dashboard (nba-admin-dashboard)

**IAM Policy:**
```yaml
bindings:
- members:
  - allUsers                      # ❌ ANYONE on internet
  role: roles/run.invoker
```

**Impact:**
- Unauthorized access to admin functions
- Data exposure
- Configuration changes

---

### ✅ Secure Services (Reference)

#### Phase 2: Raw Processors
```yaml
bindings:
- members:
  - serviceAccount:756957797294-compute@developer.gserviceaccount.com
  - serviceAccount:scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com
  - serviceAccount:service-756957797294@gcp-sa-pubsub.iam.gserviceaccount.com
  role: roles/run.invoker
```

#### Phase 3: Analytics
```yaml
bindings:
- members:
  - serviceAccount:756957797294-compute@developer.gserviceaccount.com
  - serviceAccount:scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com
  - serviceAccount:service-756957797294@gcp-sa-pubsub.iam.gserviceaccount.com
  role: roles/run.invoker
```

**These are the CORRECT security posture.**

---

## Remediation Plan

### Step 1: Immediate Lockdown (5 minutes)

**Phase 4 Precompute:**
```bash
gcloud run services remove-iam-policy-binding nba-phase4-precompute-processors \
  --region=us-west2 --member=allUsers --role=roles/run.invoker

gcloud run services remove-iam-policy-binding nba-phase4-precompute-processors \
  --region=us-west2 --member=allAuthenticatedUsers --role=roles/run.invoker

gcloud run services add-iam-policy-binding nba-phase4-precompute-processors \
  --region=us-west2 \
  --member=serviceAccount:756957797294-compute@developer.gserviceaccount.com \
  --role=roles/run.invoker
```

**Phase 5 Coordinator:**
```bash
gcloud run services remove-iam-policy-binding prediction-coordinator \
  --region=us-west2 --member=allUsers --role=roles/run.invoker

gcloud run services add-iam-policy-binding prediction-coordinator \
  --region=us-west2 \
  --member=serviceAccount:756957797294-compute@developer.gserviceaccount.com \
  --role=roles/run.invoker
```

**Phase 5 Worker:**
```bash
gcloud run services remove-iam-policy-binding prediction-worker \
  --region=us-west2 --member=allUsers --role=roles/run.invoker

gcloud run services add-iam-policy-binding prediction-worker \
  --region=us-west2 \
  --member=serviceAccount:756957797294-compute@developer.gserviceaccount.com \
  --role=roles/run.invoker

gcloud run services add-iam-policy-binding prediction-worker \
  --region=us-west2 \
  --member=serviceAccount:service-756957797294@gcp-sa-pubsub.iam.gserviceaccount.com \
  --role=roles/run.invoker
```

**Phase 1 Scrapers:**
```bash
gcloud run services remove-iam-policy-binding nba-phase1-scrapers \
  --region=us-west2 --member=allUsers --role=roles/run.invoker

gcloud run services add-iam-policy-binding nba-phase1-scrapers \
  --region=us-west2 \
  --member=serviceAccount:756957797294-compute@developer.gserviceaccount.com \
  --role=roles/run.invoker

gcloud run services add-iam-policy-binding nba-phase1-scrapers \
  --region=us-west2 \
  --member=serviceAccount:scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com \
  --role=roles/run.invoker

gcloud run services add-iam-policy-binding nba-phase1-scrapers \
  --region=us-west2 \
  --member=serviceAccount:service-756957797294@gcp-sa-pubsub.iam.gserviceaccount.com \
  --role=roles/run.invoker
```

**Admin Dashboard:**
```bash
gcloud run services remove-iam-policy-binding nba-admin-dashboard \
  --region=us-west2 --member=allUsers --role=roles/run.invoker

gcloud run services add-iam-policy-binding nba-admin-dashboard \
  --region=us-west2 \
  --member=serviceAccount:756957797294-compute@developer.gserviceaccount.com \
  --role=roles/run.invoker

gcloud run services add-iam-policy-binding nba-admin-dashboard \
  --region=us-west2 \
  --member=serviceAccount:scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com \
  --role=roles/run.invoker
```

### Step 2: Run All Commands (Batch Script)

Save this as `fix-security.sh`:

```bash
#!/bin/bash
set -e

echo "🔒 Securing Cloud Run services..."

# Phase 1
echo "Securing Phase 1 Scrapers..."
gcloud run services remove-iam-policy-binding nba-phase1-scrapers \
  --region=us-west2 --member=allUsers --role=roles/run.invoker --quiet

gcloud run services add-iam-policy-binding nba-phase1-scrapers \
  --region=us-west2 \
  --member=serviceAccount:756957797294-compute@developer.gserviceaccount.com \
  --role=roles/run.invoker --quiet

gcloud run services add-iam-policy-binding nba-phase1-scrapers \
  --region=us-west2 \
  --member=serviceAccount:scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com \
  --role=roles/run.invoker --quiet

gcloud run services add-iam-policy-binding nba-phase1-scrapers \
  --region=us-west2 \
  --member=serviceAccount:service-756957797294@gcp-sa-pubsub.iam.gserviceaccount.com \
  --role=roles/run.invoker --quiet

# Phase 4
echo "Securing Phase 4 Precompute..."
gcloud run services remove-iam-policy-binding nba-phase4-precompute-processors \
  --region=us-west2 --member=allUsers --role=roles/run.invoker --quiet

gcloud run services remove-iam-policy-binding nba-phase4-precompute-processors \
  --region=us-west2 --member=allAuthenticatedUsers --role=roles/run.invoker --quiet

gcloud run services add-iam-policy-binding nba-phase4-precompute-processors \
  --region=us-west2 \
  --member=serviceAccount:756957797294-compute@developer.gserviceaccount.com \
  --role=roles/run.invoker --quiet

# Phase 5 Coordinator
echo "Securing Phase 5 Coordinator..."
gcloud run services remove-iam-policy-binding prediction-coordinator \
  --region=us-west2 --member=allUsers --role=roles/run.invoker --quiet

gcloud run services add-iam-policy-binding prediction-coordinator \
  --region=us-west2 \
  --member=serviceAccount:756957797294-compute@developer.gserviceaccount.com \
  --role=roles/run.invoker --quiet

# Phase 5 Worker
echo "Securing Phase 5 Worker..."
gcloud run services remove-iam-policy-binding prediction-worker \
  --region=us-west2 --member=allUsers --role=roles/run.invoker --quiet

gcloud run services add-iam-policy-binding prediction-worker \
  --region=us-west2 \
  --member=serviceAccount:756957797294-compute@developer.gserviceaccount.com \
  --role=roles/run.invoker --quiet

gcloud run services add-iam-policy-binding prediction-worker \
  --region=us-west2 \
  --member=serviceAccount:service-756957797294@gcp-sa-pubsub.iam.gserviceaccount.com \
  --role=roles/run.invoker --quiet

# Admin Dashboard
echo "Securing Admin Dashboard..."
gcloud run services remove-iam-policy-binding nba-admin-dashboard \
  --region=us-west2 --member=allUsers --role=roles/run.invoker --quiet

gcloud run services add-iam-policy-binding nba-admin-dashboard \
  --region=us-west2 \
  --member=serviceAccount:756957797294-compute@developer.gserviceaccount.com \
  --role=roles/run.invoker --quiet

gcloud run services add-iam-policy-binding nba-admin-dashboard \
  --region=us-west2 \
  --member=serviceAccount:scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com \
  --role=roles/run.invoker --quiet

echo "✅ All services secured!"
echo ""
echo "Verifying security (should all return 403)..."
curl -s -o /dev/null -w "Phase 1: %{http_code}\n" https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/health
curl -s -o /dev/null -w "Phase 4: %{http_code}\n" https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/health
curl -s -o /dev/null -w "Phase 5 Coordinator: %{http_code}\n" https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/health
curl -s -o /dev/null -w "Phase 5 Worker: %{http_code}\n" https://prediction-worker-f7p3g7f6ya-wl.a.run.app/health
curl -s -o /dev/null -w "Admin Dashboard: %{http_code}\n" https://nba-admin-dashboard-f7p3g7f6ya-wl.a.run.app/health
```

### Step 3: Verify (5 minutes)

```bash
# All should return 403 Forbidden
curl -s https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/health
curl -s https://nba-phase4-precompute-processors-756957797294.us-west2.run.app/health
curl -s https://prediction-coordinator-756957797294.us-west2.run.app/health
curl -s https://prediction-worker-756957797294.us-west2.run.app/health
curl -s https://nba-admin-dashboard-f7p3g7f6ya-wl.a.run.app/health

# Test with auth token - should work
TOKEN=$(gcloud auth print-identity-token)
curl -s -H "Authorization: Bearer $TOKEN" https://nba-phase4-precompute-processors-756957797294.us-west2.run.app/health
# Expected: {"service":"precompute","status":"healthy",...}
```

---

## Root Cause Analysis

**Why did this happen?**

1. **Development Debugging:** Services were likely opened for easier testing/debugging
2. **No Security Review:** Public access was never reverted after debugging
3. **Inconsistent Practices:** Some services secured (Phase 2, 3), others not
4. **Missing Documentation:** No security checklist for deployments

**Evidence:**
- Phase 2 and 3 are properly secured → Shows knowledge of correct pattern
- Phase 1, 4, 5 are public → Suggests intentional opening for debugging
- Never reverted → No deployment security checklist

---

## Prevention Measures

### 1. Infrastructure as Code
Move IAM policies to Terraform/deployment configs:
```terraform
resource "google_cloud_run_service_iam_member" "invoker" {
  service  = google_cloud_run_service.service.name
  location = google_cloud_run_service.service.location
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.service_account_email}"
}
```

### 2. Deployment Checklist
Add to deployment scripts:
```bash
# Verify IAM policy after deployment
POLICY=$(gcloud run services get-iam-policy $SERVICE_NAME --region=$REGION)
if echo "$POLICY" | grep -q "allUsers"; then
  echo "❌ SECURITY: Service has public access!"
  exit 1
fi
```

### 3. Security Scanning
Implement automated security checks:
- Cloud Asset Inventory
- Cloud Security Command Center
- Custom scripts in CI/CD

### 4. Documentation
- Add security section to deployment guide
- Document standard IAM policy for each service type
- Require security review for IAM changes

---

## Impact Assessment

**Current Exposure:**
- Services deployed: Unknown date (likely months)
- Public access duration: Unknown
- Potential malicious access: Unknown (check Cloud Logging)

**Recommended Actions:**
1. **Immediate:** Lock down all services (above)
2. **Within 24h:** Audit Cloud Logging for suspicious access patterns
3. **Within 1 week:** Review all BigQuery costs for anomalies
4. **Within 1 week:** Implement IAM policy monitoring

**Check for malicious access:**
```bash
# Check recent access logs
gcloud logging read \
  'resource.type="cloud_run_revision"
   AND httpRequest.remoteIp!~"^10\."
   AND httpRequest.remoteIp!~"^172\."' \
  --limit=100 \
  --format=json \
  > suspicious-access.json

# Analyze IPs and patterns
cat suspicious-access.json | jq '.[] | {ip: .httpRequest.remoteIp, path: .httpRequest.requestUrl, status: .httpRequest.status}'
```

---

## Questions for Owner

1. **When were these services made public?** Check deployment history
2. **Was this intentional for testing?** If so, why not reverted?
3. **Any known security incidents?** Unusual bills, data anomalies?
4. **Who has access to deployment?** Limit to security-aware team members
5. **Monitoring in place?** Alerts for public service access?

---

## Status

- [x] Vulnerabilities identified
- [x] Remediation plan created
- [ ] **Remediation executed (URGENT)**
- [ ] Verification completed
- [ ] Monitoring implemented
- [ ] Prevention measures added

---

*Generated: 2025-12-31*
*Auditor: Claude Opus 4.5*
*Classification: CONFIDENTIAL*
