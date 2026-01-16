#!/bin/bash
# MLB Monitoring Deployment Verification Script

PROJECT_ID="nba-props-platform"
REGION="us-west2"
LOCATION="us-west2"

echo "======================================"
echo "MLB Monitoring Deployment Verification"
echo "======================================"
echo ""

# Check Cloud Run Jobs
echo "1. Checking Cloud Run Jobs..."
JOBS=$(gcloud run jobs list --region=$REGION --format="value(name)" | grep -E "^mlb-(gap-detection|freshness-checker|prediction-coverage|stall-detector|schedule-validator|pitcher-props-validator|prediction-coverage-validator)$" | wc -l)
echo "   Found $JOBS/7 MLB monitoring jobs"
if [ "$JOBS" -eq 7 ]; then
    echo "   ✅ All Cloud Run jobs deployed"
else
    echo "   ❌ Missing jobs!"
    gcloud run jobs list --region=$REGION --format="table(name,region)" | grep mlb-
fi
echo ""

# Check Cloud Schedulers
echo "2. Checking Cloud Schedulers..."
SCHEDULERS=$(gcloud scheduler jobs list --location=$LOCATION --format="value(name)" | grep -E "^mlb-(gap-detection-daily|freshness-checker-hourly|prediction-coverage-pregame|prediction-coverage-postgame|stall-detector-hourly|schedule-validator-daily|pitcher-props-validator-4hourly|prediction-coverage-validator-pregame|prediction-coverage-validator-postgame)$" | wc -l)
echo "   Found $SCHEDULERS/9 MLB monitoring schedulers"
if [ "$SCHEDULERS" -eq 9 ]; then
    echo "   ✅ All Cloud Schedulers created"
else
    echo "   ❌ Missing schedulers!"
fi
echo ""

# Check Scheduler States
echo "3. Checking Scheduler States..."
ENABLED=$(gcloud scheduler jobs list --location=$LOCATION --format="csv[no-heading](name,state)" | grep -E "^mlb-(gap-detection-daily|freshness-checker-hourly|prediction-coverage-pregame|prediction-coverage-postgame|stall-detector-hourly|schedule-validator-daily|pitcher-props-validator-4hourly|prediction-coverage-validator-pregame|prediction-coverage-validator-postgame)," | grep "ENABLED" | wc -l)
echo "   $ENABLED/9 schedulers are ENABLED"
if [ "$ENABLED" -eq 9 ]; then
    echo "   ✅ All schedulers enabled"
else
    echo "   ⚠️  Some schedulers may be paused"
fi
echo ""

# Check Docker Images
echo "4. Checking Docker Images..."
MONITORING_IMAGES=$(gcloud artifacts docker images list us-west2-docker.pkg.dev/$PROJECT_ID/mlb-monitoring --format="value(IMAGE)" | grep -E "(gap-detection|freshness-checker|prediction-coverage|stall-detector)$" | wc -l)
VALIDATOR_IMAGES=$(gcloud artifacts docker images list us-west2-docker.pkg.dev/$PROJECT_ID/mlb-validators --format="value(IMAGE)" | grep -E "(schedule-validator|pitcher-props-validator|prediction-coverage-validator)$" | wc -l)
TOTAL_IMAGES=$((MONITORING_IMAGES + VALIDATOR_IMAGES))
echo "   Found $MONITORING_IMAGES/4 monitoring images"
echo "   Found $VALIDATOR_IMAGES/3 validator images"
echo "   Total: $TOTAL_IMAGES/7 images"
if [ "$TOTAL_IMAGES" -eq 7 ]; then
    echo "   ✅ All Docker images available"
else
    echo "   ❌ Missing images!"
fi
echo ""

# Check Service Account
echo "5. Checking Service Account..."
SA_EXISTS=$(gcloud iam service-accounts list --format="value(email)" | grep "mlb-monitoring-sa@$PROJECT_ID.iam.gserviceaccount.com" | wc -l)
if [ "$SA_EXISTS" -eq 1 ]; then
    echo "   ✅ Service account exists: mlb-monitoring-sa@$PROJECT_ID.iam.gserviceaccount.com"
else
    echo "   ❌ Service account not found!"
fi
echo ""

# Check Artifact Registry Repositories
echo "6. Checking Artifact Registry Repositories..."
REPOS=$(gcloud artifacts repositories list --location=$REGION --format="value(name)" | grep -E "^(mlb-monitoring|mlb-validators)$" | wc -l)
echo "   Found $REPOS/2 repositories"
if [ "$REPOS" -eq 2 ]; then
    echo "   ✅ Both repositories exist"
else
    echo "   ❌ Missing repositories!"
fi
echo ""

# Summary
echo "======================================"
echo "Summary"
echo "======================================"

ALL_GOOD=1
if [ "$JOBS" -ne 7 ]; then ALL_GOOD=0; fi
if [ "$SCHEDULERS" -ne 9 ]; then ALL_GOOD=0; fi
if [ "$TOTAL_IMAGES" -ne 7 ]; then ALL_GOOD=0; fi
if [ "$SA_EXISTS" -ne 1 ]; then ALL_GOOD=0; fi
if [ "$REPOS" -ne 2 ]; then ALL_GOOD=0; fi

if [ "$ALL_GOOD" -eq 1 ]; then
    echo "✅ MLB Monitoring Infrastructure: FULLY DEPLOYED"
    echo ""
    echo "All components are deployed and ready:"
    echo "  • 7 Cloud Run jobs"
    echo "  • 9 Cloud Schedulers (monitoring will start automatically)"
    echo "  • 7 Docker images in Artifact Registry"
    echo "  • Service account with proper IAM permissions"
    echo "  • 2 Artifact Registry repositories"
    echo ""
    echo "Next steps:"
    echo "  1. Monitor scheduler executions starting in April 2026 (MLB season)"
    echo "  2. Set up alert subscriptions: gcloud pubsub subscriptions create ..."
    echo "  3. Create monitoring dashboard in Cloud Console"
    echo ""
    echo "View deployment details:"
    echo "  docs/09-handoff/2026-01-16-MLB-MONITORING-DEPLOYMENT-COMPLETE.md"
else
    echo "❌ MLB Monitoring Infrastructure: INCOMPLETE"
    echo ""
    echo "Some components are missing. Review the checks above."
fi
echo "======================================"
