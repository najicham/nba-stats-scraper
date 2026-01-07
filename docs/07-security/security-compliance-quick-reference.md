# Security & Compliance Quick Reference

**Created:** 2026-01-03 (Session 6)
**Version:** 1.0
**Owner:** Operations & Security Team

---

## 🎯 Purpose

Quick reference guide for security policies, compliance requirements, and access control procedures for the NBA Stats Scraper platform.

---

## 🔐 ACCESS CONTROL

### Service Accounts

| Service Account | Purpose | Key Permissions | Scope |
|----------------|---------|-----------------|-------|
| `nba-scrapers@` | Phase 1 scrapers | GCS write, Pub/Sub publish | Data ingestion |
| `nba-processors@` | Phase 2-6 processors | BigQuery write, GCS read, Pub/Sub | Data processing |
| `nba-scheduler@` | Cloud Scheduler | Cloud Run invoke, Cloud Function invoke | Orchestration |
| `nba-monitoring@` | Monitoring services | BigQuery read, GCS read, Logging read | Observability |
| `nba-backfill@` | Backfill jobs | BigQuery write, GCS read | Historical data |

### Service Account Best Practices

```bash
# List all service accounts
gcloud iam service-accounts list --project=nba-props-platform

# View service account permissions
gcloud projects get-iam-policy nba-props-platform \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:nba-scrapers@"

# Create new service account (if needed)
gcloud iam service-accounts create SERVICE_NAME \
  --display-name="Display Name" \
  --description="Purpose description"

# Grant minimal required permissions
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:SERVICE_ACCOUNT@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataEditor"
```

### Human Access Control

**Principle:** Least privilege + time-bound access

**Access Tiers:**
- **Owner:** Full access (limit to 1-2 people)
- **Editor:** Deploy services, modify data
- **Viewer:** Read-only access to data/logs
- **No Access:** Default for everyone else

**Access Review Schedule:**
- Quarterly review of all permissions
- Remove access for departed team members within 24 hours
- Rotate service account keys annually

---

## 🔑 SECRETS MANAGEMENT

### Cloud Secret Manager

**Active Secrets:**
```
projects/nba-props-platform/secrets/
  ├── ODDS_API_KEY              (Odds API authentication)
  ├── SLACK_WEBHOOK_ERROR       (Error notifications)
  ├── SLACK_WEBHOOK_WARNING     (Warning notifications)
  ├── BREVO_API_KEY             (Email alerting)
  ├── NBA_API_KEY               (NBA.com API)
  └── BIGDATABALL_API_KEY       (BigDataBall API)
```

**Accessing Secrets:**
```bash
# List all secrets
gcloud secrets list --project=nba-props-platform

# View secret value (requires permission)
gcloud secrets versions access latest --secret="ODDS_API_KEY"

# Create new secret
echo -n "secret-value" | gcloud secrets create SECRET_NAME \
  --data-file=- \
  --replication-policy="automatic"

# Grant access to service account
gcloud secrets add-iam-policy-binding SECRET_NAME \
  --member="serviceAccount:SERVICE_ACCOUNT@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### Secret Rotation Policy

| Secret Type | Rotation Frequency | Owner | Last Rotated |
|-------------|-------------------|-------|--------------|
| API Keys | Annually | Engineering | [DATE] |
| Service Account Keys | Annually | Operations | [DATE] |
| Webhook URLs | As needed | Operations | N/A |
| Database Credentials | N/A (managed) | GCP | N/A |

**Rotation Procedure:**
1. Generate new secret in provider system
2. Create new version in Secret Manager
3. Deploy services with new secret
4. Verify services working
5. Delete old secret version after 7 days

---

## 🔒 DATA SECURITY

### Encryption

**Encryption at Rest:**
- ✅ BigQuery: Google-managed encryption (default)
- ✅ GCS: Google-managed encryption (default)
- ✅ Cloud Run: Encrypted container images
- ✅ Firestore: Google-managed encryption

**Encryption in Transit:**
- ✅ All HTTPS connections (TLS 1.2+)
- ✅ Service-to-service: OIDC authentication
- ✅ API endpoints: Require authentication

**Customer-Managed Encryption Keys (CMEK):**
- ❌ Not currently implemented (optional for future)

### Data Classification

| Classification | Examples | Storage Requirements | Access Control |
|----------------|----------|---------------------|----------------|
| **Public** | NBA schedules, public stats | None | Public read |
| **Internal** | Predictions, analytics | Encrypted at rest | Service accounts only |
| **Confidential** | API keys, secrets | Secret Manager | Minimal access |
| **PII** | None currently | N/A | N/A |

**Note:** System does not currently process PII (Personally Identifiable Information)

### Data Retention Policy

| Data Type | Retention Period | Deletion Method | Owner |
|-----------|-----------------|-----------------|-------|
| Raw scraped data (GCS) | 90 days | Lifecycle policy | Automated |
| BigQuery analytics | Indefinite | Manual if needed | Engineering |
| BigQuery predictions | 1 year | Manual cleanup | Engineering |
| Logs (Cloud Logging) | 90 days | Automatic | GCP |
| Backups (BigQuery exports) | 90 days | Lifecycle policy | Automated |

**Data Deletion Procedure:**
```bash
# Delete old GCS data (automated via lifecycle)
gsutil lifecycle get gs://nba-scraped-data/

# Manual deletion if needed
gsutil -m rm -r gs://nba-scraped-data/path/to/old-data/

# Delete BigQuery table
bq rm -f nba_analytics.old_table

# Delete BigQuery dataset
bq rm -r -f nba_analytics_old
```

---

## 🛡️ NETWORK SECURITY

### Cloud Run Security

**Authentication:**
- ✅ All services require authentication (no public endpoints)
- ✅ OIDC tokens for service-to-service communication
- ✅ Cloud Scheduler authenticated via service account

**Ingress Control:**
```bash
# Restrict ingress to internal traffic only
gcloud run services update SERVICE_NAME \
  --ingress=internal \
  --region=us-west2

# Allow internal and Cloud Load Balancing
gcloud run services update SERVICE_NAME \
  --ingress=internal-and-cloud-load-balancing \
  --region=us-west2
```

**IAM Permissions:**
```bash
# Grant invoker permission to service account
gcloud run services add-iam-policy-binding SERVICE_NAME \
  --member="serviceAccount:nba-scheduler@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/run.invoker" \
  --region=us-west2

# Remove public access (if accidentally enabled)
gcloud run services remove-iam-policy-binding SERVICE_NAME \
  --member="allUsers" \
  --role="roles/run.invoker" \
  --region=us-west2
```

### VPC & Firewall

**Current Setup:**
- Default VPC (no custom VPC currently)
- Cloud Run uses Google-managed VPC connector
- No custom firewall rules

**Future Considerations:**
- VPC Service Controls for enhanced security
- Private Service Connect for BigQuery
- Cloud NAT for outbound traffic control

---

## 📋 COMPLIANCE

### Compliance Frameworks

**Current Status:**
- 🟡 **GDPR:** Not applicable (no EU user data)
- 🟡 **SOC 2:** Not certified (consider for enterprise customers)
- 🟡 **ISO 27001:** Not certified
- ✅ **Google Cloud Security:** Inherits GCP certifications

**If Compliance Required:**
1. Engage compliance consultant
2. Conduct data inventory and classification
3. Implement required controls
4. Document policies and procedures
5. Conduct regular audits

### Audit Logging

**What's Logged:**
- ✅ All Cloud Run service invocations
- ✅ BigQuery queries and data modifications
- ✅ GCS file uploads/downloads
- ✅ Service account key usage
- ✅ IAM permission changes
- ✅ Secret access (Secret Manager)

**Accessing Audit Logs:**
```bash
# View recent Cloud Run invocations
gcloud logging read \
  'resource.type="cloud_run_revision" AND protoPayload.methodName="google.cloud.run.v1.Services.UpdateService"' \
  --limit=20 \
  --format="table(timestamp,protoPayload.authenticationInfo.principalEmail,resource.labels.service_name)"

# View BigQuery data modifications
gcloud logging read \
  'protoPayload.methodName=~"^google.cloud.bigquery.*insert|update|delete"' \
  --limit=20

# View IAM permission changes
gcloud logging read \
  'protoPayload.methodName=~"SetIamPolicy"' \
  --limit=20

# Export logs for compliance (long-term storage)
gcloud logging sinks create audit-logs-export \
  gs://nba-audit-logs/ \
  --log-filter='logName:"cloudaudit.googleapis.com"'
```

---

## 🚨 SECURITY INCIDENTS

### Incident Response Levels

| Level | Description | Response Time | Escalation |
|-------|-------------|---------------|------------|
| **P0** | Active security breach, data loss | Immediate | VP Engineering, Legal |
| **P1** | Potential breach, unauthorized access | <15 min | Engineering Manager |
| **P2** | Security vulnerability discovered | <4 hours | Team Lead |
| **P3** | Security improvement needed | <24 hours | Security Team |

### Incident Response Checklist

**Suspected Security Breach:**

1. **Immediate Actions (0-15 min):**
   ```bash
   # Pause all Cloud Schedulers
   gcloud scheduler jobs pause morning-operations --location=us-west2
   gcloud scheduler jobs pause real-time-business --location=us-west2

   # Disable compromised service account (if identified)
   gcloud iam service-accounts disable SERVICE_ACCOUNT@nba-props-platform.iam.gserviceaccount.com

   # Document incident start time
   echo "Security incident started: $(date)" > /tmp/security_incident_$(date +%Y%m%d).txt
   ```

2. **Assessment (15-60 min):**
   ```bash
   # Check recent IAM changes
   gcloud logging read 'protoPayload.methodName=~"SetIamPolicy"' \
     --limit=50 \
     --freshness=7d

   # Check recent service account usage
   gcloud logging read 'protoPayload.authenticationInfo.principalEmail:SERVICE_ACCOUNT@' \
     --limit=100 \
     --freshness=1d

   # Check for unauthorized data access
   bq ls --max_results=100 nba_analytics
   gsutil ls -l gs://nba-scraped-data/ | grep "$(date +%Y-%m-%d)"
   ```

3. **Containment (1-4 hours):**
   - Revoke compromised credentials
   - Remove unauthorized access
   - Isolate affected systems
   - Document all actions taken

4. **Recovery (4-24 hours):**
   - Restore from backups if needed (see DR runbook)
   - Rotate all potentially compromised secrets
   - Re-deploy services with new credentials
   - Verify system integrity

5. **Post-Incident (24-72 hours):**
   - Conduct root cause analysis
   - Document timeline and actions
   - Update security procedures
   - Notify affected parties (if required)
   - Implement preventive measures

### Security Contacts

```
Security Team Lead:  [EMAIL] [PHONE]
VP Engineering:      [EMAIL] [PHONE]
Legal/Compliance:    [EMAIL] [PHONE]
GCP Support (P1):    Open via gcloud support cases create
```

---

## 🔍 SECURITY MONITORING

### Daily Security Checks

```bash
# 1. Check for unauthorized service account creation
gcloud iam service-accounts list --format="table(email,displayName)" | grep -v "nba-"

# 2. Check for public Cloud Run endpoints
gcloud run services list --platform=managed --region=us-west2 --format="table(SERVICE,URL)"
# Then manually verify each has --no-allow-unauthenticated

# 3. Check for recent IAM permission grants
gcloud logging read 'protoPayload.methodName="SetIamPolicy"' \
  --limit=10 \
  --freshness=1d

# 4. Check Secret Manager access
gcloud logging read 'protoPayload.serviceName="secretmanager.googleapis.com"' \
  --limit=20 \
  --freshness=1d

# 5. Check for failed authentication attempts
gcloud logging read 'protoPayload.status.code!=0 AND protoPayload.authenticationInfo:*' \
  --limit=50 \
  --freshness=1d
```

### Security Metrics

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| Public endpoints | 0 | 0 | ✅ |
| Service accounts with owner role | <2 | [CHECK] | [STATUS] |
| Secrets without rotation | 0 | [CHECK] | [STATUS] |
| Failed auth attempts | <100/day | [CHECK] | [STATUS] |
| IAM changes per week | <5 | [CHECK] | [STATUS] |

---

## 🔧 SECURITY HARDENING

### Recommended Improvements

**High Priority (30 days):**
- [ ] Conduct service account permission audit
- [ ] Implement secret rotation automation
- [ ] Setup security monitoring alerts
- [ ] Document break-glass procedures
- [ ] Enable VPC Service Controls (if needed)

**Medium Priority (60 days):**
- [ ] Implement automated security scanning
- [ ] Setup penetration testing schedule
- [ ] Create security training for team
- [ ] Implement data loss prevention (DLP) scanning
- [ ] Setup SIEM integration (if required)

**Low Priority (90 days):**
- [ ] Pursue SOC 2 certification (if needed)
- [ ] Implement customer-managed encryption keys
- [ ] Setup private VPC for Cloud Run
- [ ] Implement advanced threat detection

### Security Scanning

```bash
# Scan container images for vulnerabilities (if using Container Registry)
gcloud container images list
gcloud container images describe IMAGE_NAME --show-package-vulnerability

# Scan for secrets in code (use tool like git-secrets or truffleHog)
# Install: brew install git-secrets
git secrets --scan

# Check IAM recommender for over-permissions
gcloud recommender recommendations list \
  --project=nba-props-platform \
  --recommender=google.iam.policy.Recommender \
  --location=global
```

---

## 📚 SECURITY DOCUMENTATION

### Key Documents

| Document | Location | Last Updated | Next Review |
|----------|----------|--------------|-------------|
| Security Policy | (To be created) | N/A | N/A |
| Access Control Procedures | This doc | 2026-01-03 | 2026-04-03 |
| Incident Response Plan | `docs/02-operations/incident-response.md` | [DATE] | Quarterly |
| Disaster Recovery Plan | `docs/02-operations/disaster-recovery-runbook.md` | 2026-01-03 | Quarterly |
| Data Retention Policy | This doc | 2026-01-03 | Annually |

### Compliance Checklists

**Pre-Production Checklist:**
- [x] Service accounts follow least privilege
- [x] All secrets in Secret Manager
- [x] No hardcoded credentials in code
- [x] Encryption at rest enabled
- [x] Encryption in transit enabled
- [x] Audit logging enabled
- [x] Access controls documented
- [ ] Security review completed
- [ ] Penetration test passed (if required)

**Quarterly Security Review:**
- [ ] Review all service account permissions
- [ ] Audit IAM role assignments
- [ ] Rotate secrets (per policy)
- [ ] Review audit logs for anomalies
- [ ] Update security documentation
- [ ] Test incident response procedures
- [ ] Verify backup/recovery procedures

---

## 🆘 BREAK-GLASS PROCEDURES

### Emergency Access

**Scenario:** Need immediate access but usual access methods failing

**Break-Glass Account:**
- Email: `nba-emergency-admin@nba-props-platform.iam.gserviceaccount.com`
- Use case: Emergency recovery only
- Permissions: Owner (full access)
- Monitoring: All actions logged and alerted

**Activation:**
```bash
# 1. Document why break-glass access is needed
echo "Break-glass activated: [REASON]" >> /tmp/break_glass_$(date +%Y%m%d).txt
echo "Activated by: [YOUR NAME]" >> /tmp/break_glass_$(date +%Y%m%d).txt
echo "Time: $(date)" >> /tmp/break_glass_$(date +%Y%m%d).txt

# 2. Notify team immediately
# Send message to #nba-incidents Slack channel

# 3. Use emergency service account key (stored in secure location)
gcloud auth activate-service-account \
  --key-file=/secure/location/nba-emergency-admin-key.json

# 4. Perform emergency actions

# 5. Document all actions taken
echo "Actions taken: [DETAILED LIST]" >> /tmp/break_glass_$(date +%Y%m%d).txt

# 6. Deactivate and rotate emergency key
gcloud iam service-accounts keys delete KEY_ID \
  --iam-account=nba-emergency-admin@nba-props-platform.iam.gserviceaccount.com

# 7. Create incident report
cp /tmp/break_glass_$(date +%Y%m%d).txt \
   docs/incidents/break-glass-$(date +%Y%m%d).md
```

**Post-Break-Glass:**
- Document all actions in incident report
- Conduct post-mortem within 48 hours
- Rotate emergency credentials
- Update procedures if gaps identified

---

## 📞 CONTACTS

### Security Team

```
Security Lead:        [NAME] [EMAIL] [PHONE]
Cloud Security:       [NAME] [EMAIL] [PHONE]
Compliance Officer:   [NAME] [EMAIL] [PHONE]
Legal Counsel:        [NAME] [EMAIL] [PHONE]
```

### External Contacts

```
GCP Security Team:    security@google.com
GCP Support (P1):     Via gcloud support cases
Google Bug Bounty:    bughunter.google.com (if applicable)
```

---

## 🔄 VERSION CONTROL

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-03 | Operations Team | Initial security quick reference (Session 6) |

---

## 📖 RELATED DOCUMENTATION

- **Incident Response:** `docs/02-operations/incident-response.md`
- **Disaster Recovery:** `docs/02-operations/disaster-recovery-runbook.md`
- **Operations Dashboard:** `bin/operations/README.md`
- **Production Readiness:** `docs/02-operations/production-readiness-assessment.md`

---

**END OF SECURITY & COMPLIANCE QUICK REFERENCE**
