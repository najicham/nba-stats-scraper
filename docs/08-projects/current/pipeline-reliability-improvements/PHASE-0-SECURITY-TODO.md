# Phase 0: Security Emergency TODO List

**CRITICAL - Execute Within 24 Hours**
**Total Time:** 8 hours
**Status:** 🔴 URGENT - Security Breach Active
**Date Created:** January 18, 2026

---

## 🚨 SITUATION

**SECURITY BREACH DISCOVERED:**
- API keys and passwords exposed in `.env` file
- File is tracked in git repository
- Secrets visible in commit history
- Must rotate all credentials and secure immediately

**Exposed Secrets:**
- Odds API Key
- Ball Don't Lie API Key
- Brevo SMTP Password
- AWS SES Secret Access Key
- Anthropic API Key
- Slack Webhook URL

---

## ✅ TODO LIST (8 hours total)

### STEP 1: Rotate All Secrets (2 hours)

**Time:** 30 minutes
**Priority:** P0 - CRITICAL

#### ☐ 1.1 Rotate Odds API Key (15 min)
```bash
# Login to Odds API dashboard
open https://the-odds-api.com/account

# Steps:
# 1. Login with credentials
# 2. Navigate to API Keys section
# 3. Click "Regenerate API Key"
# 4. Save new key to secure location (password manager)
# 5. Test new key works:
curl "https://api.the-odds-api.com/v4/sports?apiKey=NEW_KEY_HERE"
```

**Record new key:** `ODDS_API_KEY_NEW=___________________`

---

#### ☐ 1.2 Rotate Ball Don't Lie API Key (20 min)
```bash
# Email BDL support to rotate key
# Template:

To: support@balldontlie.io
Subject: API Key Rotation Request - Security Incident

Hello,

We experienced a security incident where our API key was exposed.
We need to rotate our API key immediately.

Account email: [YOUR_EMAIL]
Current key (last 4 chars): c8uc

Please invalidate the current key and provide a new one.

Thank you,
[YOUR_NAME]

# Alternative: Check if they have a dashboard
# (They may have added one since last check)
```

**Record new key:** `BDL_API_KEY_NEW=___________________`

---

#### ☐ 1.3 Rotate Brevo SMTP Password (15 min)
```bash
# Login to Brevo
open https://app.brevo.com/

# Steps:
# 1. Login
# 2. Settings → SMTP & API
# 3. Click "Create a new SMTP key"
# 4. Name: "NBA Props Platform - 2026-01-18"
# 5. Copy new SMTP key
# 6. Delete old SMTP key
```

**Record new password:** `BREVO_SMTP_PASSWORD_NEW=___________________`

---

#### ☐ 1.4 Rotate AWS SES Secret Access Key (20 min)
```bash
# Rotate AWS IAM credentials
aws iam list-access-keys --user-name nba-props-ses-user

# Create new access key
aws iam create-access-key --user-name nba-props-ses-user > new-aws-key.json

# Record the keys from output
cat new-aws-key.json

# Deactivate old key (DON'T DELETE YET - in case we need rollback)
aws iam update-access-key \
  --user-name nba-props-ses-user \
  --access-key-id AKIAT... \
  --status Inactive

# After verifying new key works, delete old key:
# aws iam delete-access-key --user-name nba-props-ses-user --access-key-id AKIAT...
```

**Record new keys:**
```
AWS_SES_ACCESS_KEY_ID_NEW=___________________
AWS_SES_SECRET_ACCESS_KEY_NEW=___________________
```

---

#### ☐ 1.5 Rotate Anthropic API Key (15 min)
```bash
# Login to Anthropic Console
open https://console.anthropic.com/

# Steps:
# 1. Login
# 2. Settings → API Keys
# 3. Click "Create Key"
# 4. Name: "NBA Props Platform - 2026-01-18"
# 5. Copy new key
# 6. Delete old key (starts with sk-ant-api03-ORHMLGN2...)
```

**Record new key:** `ANTHROPIC_API_KEY_NEW=___________________`

---

#### ☐ 1.6 Rotate Slack Webhook URL (15 min)
```bash
# Login to Slack workspace
open https://api.slack.com/apps

# Steps:
# 1. Find your app or Incoming Webhook
# 2. Delete old webhook
# 3. Create new webhook
# 4. Select channel
# 5. Copy new webhook URL
```

**Record new URL:** `SLACK_WEBHOOK_URL_NEW=___________________`

---

### STEP 2: Create Secrets in GCP Secret Manager (1.5 hours)

**Time:** 1.5 hours
**Priority:** P0 - CRITICAL

#### ☐ 2.1 Install Google Cloud SDK (if needed) (10 min)
```bash
# Check if gcloud is installed
gcloud --version

# If not installed:
# macOS:
brew install google-cloud-sdk

# Linux:
curl https://sdk.cloud.google.com | bash
exec -l $SHELL

# Authenticate
gcloud auth login
gcloud config set project nba-props-platform
```

---

#### ☐ 2.2 Enable Secret Manager API (5 min)
```bash
# Enable the API
gcloud services enable secretmanager.googleapis.com

# Verify it's enabled
gcloud services list --enabled | grep secretmanager
```

---

#### ☐ 2.3 Create All Secrets in Secret Manager (30 min)
```bash
# Create script to add all secrets
cat > /tmp/create_secrets.sh << 'EOF'
#!/bin/bash
set -e

PROJECT_ID="nba-props-platform"

echo "Creating secrets in GCP Secret Manager..."

# Helper function
create_secret() {
  local secret_name=$1
  local secret_value=$2

  echo "Creating secret: $secret_name"

  # Check if secret exists
  if gcloud secrets describe $secret_name --project=$PROJECT_ID 2>/dev/null; then
    echo "  Secret exists, adding new version"
    echo -n "$secret_value" | gcloud secrets versions add $secret_name \
      --data-file=- \
      --project=$PROJECT_ID
  else
    echo "  Creating new secret"
    echo -n "$secret_value" | gcloud secrets create $secret_name \
      --data-file=- \
      --replication-policy="automatic" \
      --project=$PROJECT_ID
  fi

  echo "  ✓ $secret_name created/updated"
}

# Create all secrets (REPLACE WITH YOUR NEW VALUES)
create_secret "odds-api-key" "YOUR_NEW_ODDS_API_KEY_HERE"
create_secret "bdl-api-key" "YOUR_NEW_BDL_API_KEY_HERE"
create_secret "brevo-smtp-password" "YOUR_NEW_BREVO_PASSWORD_HERE"
create_secret "aws-ses-access-key-id" "YOUR_NEW_AWS_ACCESS_KEY_ID_HERE"
create_secret "aws-ses-secret-access-key" "YOUR_NEW_AWS_SECRET_KEY_HERE"
create_secret "anthropic-api-key" "YOUR_NEW_ANTHROPIC_KEY_HERE"
create_secret "slack-webhook-url" "YOUR_NEW_SLACK_WEBHOOK_HERE"

echo ""
echo "✓ All secrets created successfully!"
echo ""
echo "Verifying secrets..."

# List all secrets
gcloud secrets list --project=$PROJECT_ID

EOF

# Edit the script with your new secret values
nano /tmp/create_secrets.sh

# Make executable and run
chmod +x /tmp/create_secrets.sh
/tmp/create_secrets.sh

# Verify secrets were created
gcloud secrets list --project=nba-props-platform
```

---

#### ☐ 2.4 Grant Service Accounts Access to Secrets (30 min)
```bash
# List all service accounts that need access
gcloud iam service-accounts list --project=nba-props-platform

# Grant access to each service account
# Replace SERVICE_ACCOUNT_EMAIL with actual emails

cat > /tmp/grant_secret_access.sh << 'EOF'
#!/bin/bash
set -e

PROJECT_ID="nba-props-platform"
SECRETS=(
  "odds-api-key"
  "bdl-api-key"
  "brevo-smtp-password"
  "aws-ses-access-key-id"
  "aws-ses-secret-access-key"
  "anthropic-api-key"
  "slack-webhook-url"
)

# Service accounts that need access
# ADD YOUR SERVICE ACCOUNT EMAILS HERE
SERVICE_ACCOUNTS=(
  "prediction-worker@nba-props-platform.iam.gserviceaccount.com"
  "prediction-coordinator@nba-props-platform.iam.gserviceaccount.com"
  "scrapers@nba-props-platform.iam.gserviceaccount.com"
  # Add more service accounts as needed
)

echo "Granting secret access to service accounts..."

for secret in "${SECRETS[@]}"; do
  for sa in "${SERVICE_ACCOUNTS[@]}"; do
    echo "Granting $sa access to $secret"
    gcloud secrets add-iam-policy-binding $secret \
      --member="serviceAccount:$sa" \
      --role="roles/secretmanager.secretAccessor" \
      --project=$PROJECT_ID
  done
done

echo "✓ Access granted!"
EOF

# Edit to add your service accounts
nano /tmp/grant_secret_access.sh

chmod +x /tmp/grant_secret_access.sh
/tmp/grant_secret_access.sh
```

---

#### ☐ 2.5 Test Secret Access (15 min)
```bash
# Test reading a secret
gcloud secrets versions access latest --secret="odds-api-key"

# Should output the secret value
# If you get permission denied, check IAM bindings

# Test from Python (as services will use it)
python3 << 'EOF'
from google.cloud import secretmanager

client = secretmanager.SecretManagerServiceClient()
project_id = "nba-props-platform"
secret_name = "odds-api-key"

name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
response = client.access_secret_version(request={"name": name})
secret_value = response.payload.data.decode('UTF-8')

print(f"✓ Successfully retrieved secret: {secret_value[:10]}...")
EOF
```

---

### STEP 3: Update Code to Use Secret Manager (2.5 hours)

**Time:** 2.5 hours
**Priority:** P0 - CRITICAL

#### ☐ 3.1 Create Secret Manager Utility Class (30 min)
```bash
cd /home/naji/code/nba-stats-scraper

# Create the utility file
cat > shared/utils/secrets.py << 'EOF'
"""
Centralized secret management using GCP Secret Manager.

Usage:
    from shared.utils.secrets import get_secret_manager

    secrets = get_secret_manager()
    api_key = secrets.get_odds_api_key()
"""

from google.cloud import secretmanager
from functools import lru_cache
import os
import logging

logger = logging.getLogger(__name__)


class SecretManager:
    """Centralized secret management using GCP Secret Manager."""

    def __init__(self):
        self.project_id = os.environ.get('PROJECT_ID', 'nba-props-platform')
        self.client = secretmanager.SecretManagerServiceClient()
        logger.info(f"SecretManager initialized for project: {self.project_id}")

    @lru_cache(maxsize=32)
    def get_secret(self, secret_name: str, version: str = 'latest') -> str:
        """
        Retrieve secret from Secret Manager (cached).

        Args:
            secret_name: Name of the secret
            version: Version to retrieve (default: 'latest')

        Returns:
            Secret value as string

        Raises:
            ValueError: If secret retrieval fails
        """
        name = f"projects/{self.project_id}/secrets/{secret_name}/versions/{version}"

        try:
            response = self.client.access_secret_version(request={"name": name})
            secret_value = response.payload.data.decode('UTF-8')
            logger.debug(f"Retrieved secret: {secret_name}")
            return secret_value
        except Exception as e:
            logger.error(f"Failed to retrieve secret {secret_name}: {e}")
            raise ValueError(f"Failed to retrieve secret {secret_name}: {e}")

    def get_odds_api_key(self) -> str:
        """Get Odds API key."""
        return self.get_secret('odds-api-key')

    def get_bdl_api_key(self) -> str:
        """Get Ball Don't Lie API key."""
        return self.get_secret('bdl-api-key')

    def get_brevo_smtp_password(self) -> str:
        """Get Brevo SMTP password."""
        return self.get_secret('brevo-smtp-password')

    def get_aws_ses_access_key_id(self) -> str:
        """Get AWS SES access key ID."""
        return self.get_secret('aws-ses-access-key-id')

    def get_aws_ses_secret_key(self) -> str:
        """Get AWS SES secret access key."""
        return self.get_secret('aws-ses-secret-access-key')

    def get_anthropic_api_key(self) -> str:
        """Get Anthropic API key."""
        return self.get_secret('anthropic-api-key')

    def get_slack_webhook_url(self) -> str:
        """Get Slack webhook URL."""
        return self.get_secret('slack-webhook-url')


# Singleton instance
_secret_manager = None


def get_secret_manager() -> SecretManager:
    """Get singleton SecretManager instance."""
    global _secret_manager
    if _secret_manager is None:
        _secret_manager = SecretManager()
    return _secret_manager
EOF

# Add to git
git add shared/utils/secrets.py
```

---

#### ☐ 3.2 Find All .env Usage in Code (20 min)
```bash
cd /home/naji/code/nba-stats-scraper

# Search for all environment variable usage
echo "=== Searching for .env usage ==="

# Find ODDS_API_KEY usage
echo "ODDS_API_KEY references:"
grep -r "ODDS_API_KEY" --include="*.py" . | wc -l

# Find BDL_API_KEY usage
echo "BDL_API_KEY references:"
grep -r "BDL_API_KEY" --include="*.py" . | wc -l

# Find all secret references
for secret in ODDS_API_KEY BDL_API_KEY BREVO_SMTP_PASSWORD AWS_SES_SECRET_ACCESS_KEY ANTHROPIC_API_KEY SLACK_WEBHOOK_URL; do
  echo ""
  echo "=== $secret ==="
  grep -r "$secret" --include="*.py" -n . | head -5
done

# Save to file for reference
grep -r "os.environ.get\|os.getenv" --include="*.py" . > /tmp/env_usage.txt
echo "Full list saved to /tmp/env_usage.txt"
```

---

#### ☐ 3.3 Update Scrapers to Use Secret Manager (40 min)
```bash
cd /home/naji/code/nba-stats-scraper

# Example: Update Odds API scraper
# Find the file
find . -name "*odds*scraper*.py" -type f

# Update each scraper file
# Replace:
#   api_key = os.environ.get('ODDS_API_KEY')
# With:
#   from shared.utils.secrets import get_secret_manager
#   secrets = get_secret_manager()
#   api_key = secrets.get_odds_api_key()

# You'll need to manually update each file
# Key files to update:
# - scrapers/odds_api/scraper.py
# - scrapers/bdl/scraper.py
# - Any file using the secrets

# Create a migration script
cat > /tmp/migrate_secrets.sh << 'EOF'
#!/bin/bash
# This script helps identify files that need updating
# You'll need to manually update each file

echo "Files that likely need updating:"
echo ""

echo "=== Odds API ==="
grep -l "ODDS_API_KEY" --include="*.py" -r .

echo ""
echo "=== BDL API ==="
grep -l "BDL_API_KEY" --include="*.py" -r .

echo ""
echo "=== SMTP/Email ==="
grep -l "BREVO_SMTP_PASSWORD\|SMTP_PASSWORD" --include="*.py" -r .

echo ""
echo "=== AWS SES ==="
grep -l "AWS_SES" --include="*.py" -r .

echo ""
echo "=== Anthropic ==="
grep -l "ANTHROPIC_API_KEY" --include="*.py" -r .

echo ""
echo "=== Slack ==="
grep -l "SLACK_WEBHOOK" --include="*.py" -r .
EOF

chmod +x /tmp/migrate_secrets.sh
/tmp/migrate_secrets.sh
```

**Manual Steps for Each File:**
1. Add import: `from shared.utils.secrets import get_secret_manager`
2. Add initialization: `secrets = get_secret_manager()`
3. Replace env var access with method call
4. Test the file

---

#### ☐ 3.4 Update Prediction Services (40 min)
```bash
# Update prediction worker
# File: predictions/worker/worker.py

# Update prediction coordinator
# File: predictions/coordinator/coordinator.py

# Similar pattern:
# 1. Import SecretManager
# 2. Replace os.environ.get() calls
# 3. Test
```

---

#### ☐ 3.5 Update Alert/Notification Code (20 min)
```bash
# Files that use SMTP or Slack webhooks
# - shared/alerting/email_sender.py (if exists)
# - shared/alerting/slack_notifier.py (if exists)

# Update each to use SecretManager
```

---

### STEP 4: Remove .env from Git History (1.5 hours)

**Time:** 1.5 hours
**Priority:** P0 - CRITICAL
**⚠️ WARNING:** This rewrites git history - coordinate with team first!

#### ☐ 4.1 Backup Repository (10 min)
```bash
cd /home/naji/code/nba-stats-scraper

# Create backup
cd ..
cp -r nba-stats-scraper nba-stats-scraper-backup-$(date +%Y%m%d)

echo "✓ Backup created"
```

---

#### ☐ 4.2 Add .env to .gitignore (5 min)
```bash
cd /home/naji/code/nba-stats-scraper

# Add to .gitignore
cat >> .gitignore << 'EOF'

# Environment files (NEVER COMMIT)
.env
.env.local
.env.*.local
.env.production
.env.development
EOF

# Commit .gitignore update
git add .gitignore
git commit -m "security: Add .env files to .gitignore"
```

---

#### ☐ 4.3 Create .env.example Template (10 min)
```bash
# Create example file WITHOUT actual secrets
cat > .env.example << 'EOF'
# NBA Props Platform - Environment Configuration
# DO NOT COMMIT ACTUAL VALUES - All secrets should be in GCP Secret Manager

# Project Configuration
PROJECT_ID=nba-props-platform
ENVIRONMENT=production

# Secret Manager References (not actual values)
# Actual secrets are stored in GCP Secret Manager:
# - odds-api-key
# - bdl-api-key
# - brevo-smtp-password
# - aws-ses-access-key-id
# - aws-ses-secret-access-key
# - anthropic-api-key
# - slack-webhook-url

# For local development, set these to reference Secret Manager:
USE_SECRET_MANAGER=true
EOF

git add .env.example
git commit -m "security: Add .env.example template"
```

---

#### ☐ 4.4 Remove .env from Git History (30 min)
```bash
cd /home/naji/code/nba-stats-scraper

# ⚠️ COORDINATE WITH TEAM BEFORE RUNNING THIS
# This rewrites history - all team members need to re-clone

# Install git-filter-repo (better than filter-branch)
# macOS:
brew install git-filter-repo

# Linux:
pip3 install git-filter-repo

# Remove .env from history
git filter-repo --path .env --invert-paths --force

# Alternative using git-filter-branch (if git-filter-repo not available):
# git filter-branch --force --index-filter \
#   "git rm --cached --ignore-unmatch .env" \
#   --prune-empty --tag-name-filter cat -- --all
```

---

#### ☐ 4.5 Force Push to Remote (15 min)
```bash
# ⚠️ CRITICAL: Coordinate with team first!
# Everyone needs to re-clone after this

# Check what will be pushed
git log --oneline --graph --all | head -20

# Force push (THIS REWRITES HISTORY)
git push origin --force --all
git push origin --force --tags

# Notify team to re-clone:
echo "
ATTENTION TEAM:
We removed secrets from git history. Please:
1. Backup your local changes
2. Delete your local repo
3. Re-clone from origin
4. Re-apply your local changes

Command:
git clone git@github.com:your-org/nba-stats-scraper.git
"
```

---

#### ☐ 4.6 Verify .env is Gone from History (10 min)
```bash
# Search history for .env
git log --all --full-history -- .env

# Should return nothing

# Search for secret values (check one)
git log --all -S "ODDS_API_KEY" --source --all

# Should only show recent commits removing it, not old ones with the value
```

---

### STEP 5: Deploy Updated Code (30 min)

**Time:** 30 min
**Priority:** P0 - CRITICAL

#### ☐ 5.1 Add Secret Manager Dependency (5 min)
```bash
cd /home/naji/code/nba-stats-scraper

# Add to root requirements.txt
echo "google-cloud-secret-manager==2.16.0" >> requirements.txt

# Add to each service's requirements.txt
for dir in predictions/worker predictions/coordinator scrapers data_processors/*/; do
  if [ -f "$dir/requirements.txt" ]; then
    echo "google-cloud-secret-manager==2.16.0" >> "$dir/requirements.txt"
  fi
done

git add -A
git commit -m "security: Add Secret Manager dependency"
git push
```

---

#### ☐ 5.2 Deploy to Staging First (10 min)
```bash
# Deploy to staging environment
# (Adjust based on your deployment process)

# Example for Cloud Run:
cd predictions/worker
gcloud run deploy prediction-worker-staging \
  --source=. \
  --region=us-west2 \
  --project=nba-props-platform

# Test staging
curl https://prediction-worker-staging-<hash>.run.app/health

# Check logs for any secret access errors
gcloud logging read "resource.labels.service_name=prediction-worker-staging" \
  --limit=20 \
  --format="table(timestamp,severity,textPayload)"
```

---

#### ☐ 5.3 Deploy to Production (15 min)
```bash
# Deploy each service
# Use canary deployment if script from Phase 1 is ready
# Otherwise, deploy carefully with monitoring

# Prediction worker
cd predictions/worker
gcloud run deploy prediction-worker \
  --source=. \
  --region=us-west2 \
  --project=nba-props-platform

# Prediction coordinator
cd ../coordinator
gcloud run deploy prediction-coordinator \
  --source=. \
  --region=us-west2 \
  --project=nba-props-platform

# Scrapers (if separate deployment)
cd ../../scrapers
# Deploy scraper services

# Monitor for errors
watch -n 5 'gcloud logging read "severity>=ERROR" --limit=5 --freshness=5m'
```

---

### STEP 6: Verify Everything Works (30 min)

**Time:** 30 min
**Priority:** P0 - CRITICAL

#### ☐ 6.1 Test Each Secret Access (15 min)
```bash
# Test Odds API
curl "https://api.the-odds-api.com/v4/sports?apiKey=$(gcloud secrets versions access latest --secret=odds-api-key)"

# Should return sports list

# Test BDL API
curl -H "Authorization: $(gcloud secrets versions access latest --secret=bdl-api-key)" \
  "https://api.balldontlie.io/v1/games"

# Should return games

# Test each service can access secrets
# Check application logs
```

---

#### ☐ 6.2 Run End-to-End Test (10 min)
```bash
# Trigger a prediction run
# Monitor that it completes successfully

# Check that scrapers run
# Check that predictions generate
# Check that alerts work
```

---

#### ☐ 6.3 Monitor for 24 Hours (ongoing)
```bash
# Set up monitoring
# Watch for:
# - Secret access errors
# - Authentication failures
# - Service errors

# Check logs every few hours
gcloud logging read "severity>=WARNING" \
  --limit=50 \
  --freshness=1h \
  --format="table(timestamp,resource.labels.service_name,severity,textPayload)"
```

---

## 📋 CHECKLIST SUMMARY

### Must Complete Today:
- [ ] Step 1: Rotate all 6 secrets (2 hours)
- [ ] Step 2: Create secrets in Secret Manager (1.5 hours)
- [ ] Step 3: Update code to use Secret Manager (2.5 hours)
- [ ] Step 4: Remove .env from git history (1.5 hours)
- [ ] Step 5: Deploy updated code (30 min)
- [ ] Step 6: Verify everything works (30 min)

**Total: 8 hours**

### Success Criteria:
- [ ] All secrets rotated and old ones invalidated
- [ ] All secrets in GCP Secret Manager
- [ ] No secrets in code or .env file
- [ ] .env removed from git history
- [ ] All services deployed and working
- [ ] No errors in logs related to secret access

---

## 🚨 If You Get Stuck

### Problem: Can't rotate a secret
**Solution:** Continue with others, rotate this one manually later

### Problem: Service account permission denied
**Solution:** Check IAM bindings, grant secretAccessor role

### Problem: Code breaks after migration
**Solution:** Check logs, verify secret names match, rollback if needed

### Problem: Git history rewrite fails
**Solution:** Use backup, try git-filter-branch alternative

---

## ✅ COMPLETION

After completing all steps:

1. **Verify Security:**
   ```bash
   # No secrets in code
   grep -r "ODDS_API_KEY.*=" --include="*.py" . | grep -v "secrets.get"
   # Should return nothing

   # .env not in git
   git log --all -- .env
   # Should return nothing or only removal commits
   ```

2. **Document What You Did:**
   - Update this file with completion timestamps
   - Note any issues encountered
   - Record new secret locations

3. **Update Handoff Doc:**
   - Mark Phase 0 as complete
   - Ready to start Phase 1

---

**Status After Completion:** 🟢 Security breach resolved, ready for Phase 1

---

**Created:** January 18, 2026
**Last Updated:** January 18, 2026
**Estimated Completion:** January 19, 2026
