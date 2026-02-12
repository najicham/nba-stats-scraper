#!/bin/bash
# bin/deploy-function.sh
#
# Standardized Cloud Function deployment script.
# Handles the full deploy lifecycle: package source, copy shared modules,
# deploy with gcloud functions deploy --gen2, and clean up.
#
# Session 219 lessons applied:
#   1. Uses rsync -aL (not cp -rL) to properly resolve symlinks
#   2. Copies full shared/ tree for functions that import from shared.*
#   3. Entry point defaults set per-function (Gen2 entry points are immutable)
#   4. Temp deploy dir ensures clean, flat package every time
#
# Usage:
#   ./bin/deploy-function.sh <function-name>
#   ./bin/deploy-function.sh grading-gap-detector
#   ./bin/deploy-function.sh phase3-to-phase4-orchestrator --dry-run
#   ./bin/deploy-function.sh enrichment-trigger --memory 512MB --timeout 120s
#   ./bin/deploy-function.sh validation-runner --entry-point run_validation
#
# Options:
#   --dry-run             Show what would be deployed without deploying
#   --entry-point NAME    Override the default entry point
#   --timeout DURATION    Override default timeout (e.g., 300s)
#   --memory SIZE         Override default memory (e.g., 1Gi, 512MB)
#   --service-account SA  Override default service account
#   --trigger-topic TOPIC Override default Pub/Sub trigger topic (implies Pub/Sub trigger)
#   --trigger-http        Force HTTP trigger (overrides default)
#   --allow-unauthenticated  Allow unauthenticated HTTP invocations
#   --skip-iam            Skip IAM binding step (for HTTP-only functions)
#   --verbose             Show detailed output during packaging

set -euo pipefail

# ============================================================================
# Constants
# ============================================================================

REGION="us-west2"
PROJECT="nba-props-platform"
RUNTIME="python311"
DEFAULT_SERVICE_ACCOUNT="processor-sa@nba-props-platform.iam.gserviceaccount.com"
DEFAULT_MEMORY="1Gi"
DEFAULT_TIMEOUT="300s"
MAX_INSTANCES="3"
MIN_INSTANCES="0"

# Compute service account used for Pub/Sub IAM binding
PUBSUB_INVOKER_SA="756957797294-compute@developer.gserviceaccount.com"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ============================================================================
# Ensure we run from repo root
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

# ============================================================================
# Function registry: name -> source_dir, entry_point, trigger_type, trigger_topic
# ============================================================================

get_function_config() {
    local func_name="$1"

    # Defaults
    FUNC_SOURCE_DIR=""
    FUNC_ENTRY_POINT=""
    FUNC_TRIGGER_TYPE=""
    FUNC_TRIGGER_TOPIC=""
    FUNC_NEEDS_SHARED="false"

    case "$func_name" in
        # --- Orchestrators (Pub/Sub triggered) ---
        phase3-to-phase4-orchestrator)
            FUNC_SOURCE_DIR="orchestration/cloud_functions/phase3_to_phase4"
            FUNC_ENTRY_POINT="orchestrate_phase3_to_phase4"
            FUNC_TRIGGER_TYPE="topic"
            FUNC_TRIGGER_TOPIC="nba-phase3-analytics-complete"
            FUNC_NEEDS_SHARED="true"
            ;;
        phase4-to-phase5-orchestrator)
            FUNC_SOURCE_DIR="orchestration/cloud_functions/phase4_to_phase5"
            FUNC_ENTRY_POINT="orchestrate_phase4_to_phase5"
            FUNC_TRIGGER_TYPE="topic"
            FUNC_TRIGGER_TOPIC="nba-phase4-precompute-complete"
            FUNC_NEEDS_SHARED="true"
            ;;
        phase5-to-phase6-orchestrator)
            FUNC_SOURCE_DIR="orchestration/cloud_functions/phase5_to_phase6"
            FUNC_ENTRY_POINT="orchestrate_phase5_to_phase6"
            FUNC_TRIGGER_TYPE="topic"
            FUNC_TRIGGER_TOPIC="nba-phase5-predictions-complete"
            FUNC_NEEDS_SHARED="true"
            ;;
        phase5b-grading)
            FUNC_SOURCE_DIR="orchestration/cloud_functions/grading"
            FUNC_ENTRY_POINT="main"
            FUNC_TRIGGER_TYPE="topic"
            FUNC_TRIGGER_TOPIC="nba-grading-trigger"
            FUNC_NEEDS_SHARED="true"
            ;;

        # --- Monitoring & Validation (HTTP triggered) ---
        grading-gap-detector)
            FUNC_SOURCE_DIR="orchestration/cloud_functions/grading-gap-detector"
            FUNC_ENTRY_POINT="main"
            FUNC_TRIGGER_TYPE="http"
            FUNC_NEEDS_SHARED="false"
            ;;
        daily-health-check)
            FUNC_SOURCE_DIR="orchestration/cloud_functions/daily_health_check"
            FUNC_ENTRY_POINT="daily_health_check"
            FUNC_TRIGGER_TYPE="http"
            FUNC_NEEDS_SHARED="true"
            ;;
        validation-runner)
            FUNC_SOURCE_DIR="orchestration/cloud_functions/validation_runner"
            FUNC_ENTRY_POINT="run_validation"
            FUNC_TRIGGER_TYPE="http"
            FUNC_NEEDS_SHARED="true"
            ;;
        reconcile)
            FUNC_SOURCE_DIR="orchestration/cloud_functions/prediction_monitoring"
            FUNC_ENTRY_POINT="reconcile"
            FUNC_TRIGGER_TYPE="http"
            FUNC_NEEDS_SHARED="false"
            ;;
        validate-freshness)
            FUNC_SOURCE_DIR="orchestration/cloud_functions/prediction_monitoring"
            FUNC_ENTRY_POINT="validate_freshness"
            FUNC_TRIGGER_TYPE="http"
            FUNC_NEEDS_SHARED="false"
            ;;
        pipeline-health-summary)
            FUNC_SOURCE_DIR="monitoring/health_summary"
            FUNC_ENTRY_POINT="pipeline_health_summary"
            FUNC_TRIGGER_TYPE="http"
            FUNC_NEEDS_SHARED="true"
            ;;
        transition-monitor)
            FUNC_SOURCE_DIR="orchestration/cloud_functions/transition_monitor"
            FUNC_ENTRY_POINT="main"
            FUNC_TRIGGER_TYPE="http"
            FUNC_NEEDS_SHARED="true"
            ;;
        self-heal-predictions)
            FUNC_SOURCE_DIR="orchestration/cloud_functions/self_heal"
            FUNC_ENTRY_POINT="main"
            FUNC_TRIGGER_TYPE="http"
            FUNC_NEEDS_SHARED="true"
            ;;
        live-freshness-monitor)
            FUNC_SOURCE_DIR="orchestration/cloud_functions/live_freshness_monitor"
            FUNC_ENTRY_POINT="main"
            FUNC_TRIGGER_TYPE="http"
            FUNC_NEEDS_SHARED="true"
            ;;
        enrichment-trigger)
            FUNC_SOURCE_DIR="orchestration/cloud_functions/enrichment_trigger"
            FUNC_ENTRY_POINT="trigger_enrichment"
            FUNC_TRIGGER_TYPE="http"
            FUNC_NEEDS_SHARED="true"
            ;;

        *)
            return 1
            ;;
    esac
    return 0
}

# ============================================================================
# Usage
# ============================================================================

usage() {
    echo "Usage: ./bin/deploy-function.sh <function-name> [options]"
    echo ""
    echo "Standardized Cloud Function deployment with rsync-based packaging."
    echo ""
    echo "Available functions:"
    echo "  Orchestrators (Pub/Sub triggered):"
    echo "    phase3-to-phase4-orchestrator"
    echo "    phase4-to-phase5-orchestrator"
    echo "    phase5-to-phase6-orchestrator"
    echo "    phase5b-grading"
    echo ""
    echo "  Monitoring & Validation (HTTP triggered):"
    echo "    grading-gap-detector"
    echo "    daily-health-check"
    echo "    validation-runner"
    echo "    reconcile"
    echo "    validate-freshness"
    echo "    pipeline-health-summary"
    echo "    transition-monitor"
    echo "    self-heal-predictions"
    echo "    live-freshness-monitor"
    echo "    enrichment-trigger"
    echo ""
    echo "Options:"
    echo "  --dry-run                Show what would be deployed without deploying"
    echo "  --entry-point NAME       Override the default entry point"
    echo "  --timeout DURATION       Override default timeout (default: $DEFAULT_TIMEOUT)"
    echo "  --memory SIZE            Override default memory (default: $DEFAULT_MEMORY)"
    echo "  --service-account SA     Override default service account"
    echo "  --trigger-topic TOPIC    Override/set Pub/Sub trigger topic"
    echo "  --trigger-http           Force HTTP trigger"
    echo "  --allow-unauthenticated  Allow unauthenticated HTTP invocations"
    echo "  --skip-iam               Skip IAM binding step"
    echo "  --verbose                Show detailed packaging output"
    echo ""
    echo "Examples:"
    echo "  ./bin/deploy-function.sh grading-gap-detector"
    echo "  ./bin/deploy-function.sh phase3-to-phase4-orchestrator --dry-run"
    echo "  ./bin/deploy-function.sh enrichment-trigger --memory 512MB --timeout 120s"
    echo "  ./bin/deploy-function.sh validation-runner --entry-point run_validation"
    echo "  ./bin/deploy-function.sh phase5b-grading --verbose"
    exit 1
}

# ============================================================================
# Parse arguments
# ============================================================================

if [ $# -lt 1 ]; then
    usage
fi

FUNCTION_NAME="$1"
shift

# Option defaults
DRY_RUN=false
VERBOSE=false
OPT_ENTRY_POINT=""
OPT_TIMEOUT=""
OPT_MEMORY=""
OPT_SERVICE_ACCOUNT=""
OPT_TRIGGER_TOPIC=""
OPT_TRIGGER_HTTP=false
ALLOW_UNAUTHENTICATED=false
SKIP_IAM=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        --entry-point)
            OPT_ENTRY_POINT="$2"
            shift 2
            ;;
        --timeout)
            OPT_TIMEOUT="$2"
            shift 2
            ;;
        --memory)
            OPT_MEMORY="$2"
            shift 2
            ;;
        --service-account)
            OPT_SERVICE_ACCOUNT="$2"
            shift 2
            ;;
        --trigger-topic)
            OPT_TRIGGER_TOPIC="$2"
            shift 2
            ;;
        --trigger-http)
            OPT_TRIGGER_HTTP=true
            shift
            ;;
        --allow-unauthenticated)
            ALLOW_UNAUTHENTICATED=true
            shift
            ;;
        --skip-iam)
            SKIP_IAM=true
            shift
            ;;
        *)
            echo -e "${RED}ERROR: Unknown option: $1${NC}"
            echo ""
            usage
            ;;
    esac
done

# ============================================================================
# Look up function config
# ============================================================================

if ! get_function_config "$FUNCTION_NAME"; then
    echo -e "${RED}ERROR: Unknown function: $FUNCTION_NAME${NC}"
    echo ""
    usage
fi

# Apply overrides
ENTRY_POINT="${OPT_ENTRY_POINT:-$FUNC_ENTRY_POINT}"
TIMEOUT="${OPT_TIMEOUT:-$DEFAULT_TIMEOUT}"
MEMORY="${OPT_MEMORY:-$DEFAULT_MEMORY}"
SERVICE_ACCOUNT="${OPT_SERVICE_ACCOUNT:-$DEFAULT_SERVICE_ACCOUNT}"

# Determine trigger type (CLI overrides take precedence)
if [ "$OPT_TRIGGER_HTTP" = true ]; then
    TRIGGER_TYPE="http"
    TRIGGER_TOPIC=""
elif [ -n "$OPT_TRIGGER_TOPIC" ]; then
    TRIGGER_TYPE="topic"
    TRIGGER_TOPIC="$OPT_TRIGGER_TOPIC"
else
    TRIGGER_TYPE="$FUNC_TRIGGER_TYPE"
    TRIGGER_TOPIC="${FUNC_TRIGGER_TOPIC:-}"
fi

# ============================================================================
# Validate source directory
# ============================================================================

if [ ! -d "$FUNC_SOURCE_DIR" ]; then
    echo -e "${RED}ERROR: Source directory not found: $FUNC_SOURCE_DIR${NC}"
    echo "Ensure you are running from the repository root."
    exit 1
fi

if [ ! -f "$FUNC_SOURCE_DIR/main.py" ]; then
    echo -e "${RED}ERROR: main.py not found in $FUNC_SOURCE_DIR${NC}"
    exit 1
fi

if [ ! -f "$FUNC_SOURCE_DIR/requirements.txt" ]; then
    echo -e "${RED}ERROR: requirements.txt not found in $FUNC_SOURCE_DIR${NC}"
    exit 1
fi

# ============================================================================
# Build metadata
# ============================================================================

BUILD_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
BUILD_TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# ============================================================================
# Display configuration
# ============================================================================

echo -e "${BLUE}==================================================${NC}"
echo -e "${BLUE}  Cloud Function Deploy: ${FUNCTION_NAME}${NC}"
echo -e "${BLUE}==================================================${NC}"
echo ""
echo -e "${YELLOW}Configuration:${NC}"
echo "  Function:        $FUNCTION_NAME"
echo "  Source dir:      $FUNC_SOURCE_DIR"
echo "  Entry point:     $ENTRY_POINT"
echo "  Trigger:         $TRIGGER_TYPE"
if [ "$TRIGGER_TYPE" = "topic" ]; then
    echo "  Topic:           $TRIGGER_TOPIC"
fi
echo "  Memory:          $MEMORY"
echo "  Timeout:         $TIMEOUT"
echo "  Service account: $SERVICE_ACCOUNT"
echo "  Needs shared/:   $FUNC_NEEDS_SHARED"
echo "  Region:          $REGION"
echo "  Project:         $PROJECT"
echo "  Runtime:         $RUNTIME"
echo ""
echo -e "${YELLOW}Build metadata:${NC}"
echo "  Commit:          $BUILD_COMMIT"
echo "  Timestamp:       $BUILD_TIMESTAMP"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}[DRY RUN] Showing what would be deployed...${NC}"
    echo ""
fi

# ============================================================================
# Step 1: Create deploy package
# ============================================================================

echo -e "${BLUE}[1/4] Creating deployment package...${NC}"

DEPLOY_DIR=$(mktemp -d)
trap "rm -rf $DEPLOY_DIR" EXIT

# Copy function source files (Session 219: resolves symlinks properly).
# Many function dirs contain directory-level symlinks (e.g., shared/ -> ../../../shared,
# bin -> ../../../bin) that cause rsync -aL to fail when those trees contain broken
# symlinks. We exclude those well-known dependency directories here and copy them
# separately from the repo root below, which is the clean and canonical source.
rsync -aL \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.git' \
    --exclude='tests/' \
    --exclude='docs/' \
    --exclude='shared' \
    --exclude='bin' \
    --exclude='data_processors' \
    --exclude='predictions' \
    --exclude='backfill_jobs' \
    "$FUNC_SOURCE_DIR/" "$DEPLOY_DIR/"

echo -e "  ${GREEN}Copied function source from $FUNC_SOURCE_DIR${NC}"

# Copy shared/ module tree if needed (Session 219: many functions import from shared.*)
if [ "$FUNC_NEEDS_SHARED" = "true" ] && [ -d "shared" ]; then
    rsync -aL \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='tests/' \
        --exclude='.git' \
        "shared/" "$DEPLOY_DIR/shared/"
    echo -e "  ${GREEN}Copied shared/ module tree${NC}"
fi

# Some functions also need data_processors, predictions, or backfill_jobs.
# Copy them if the function's main.py imports from those packages.
for pkg in data_processors predictions backfill_jobs; do
    if [ -d "$pkg" ] && grep -q "from ${pkg}" "$DEPLOY_DIR/main.py" 2>/dev/null; then
        rsync -aL \
            --exclude='__pycache__' \
            --exclude='*.pyc' \
            --exclude='tests/' \
            --exclude='.git' \
            --exclude='Dockerfile' \
            --exclude='*.md' \
            "$pkg/" "$DEPLOY_DIR/$pkg/"
        echo -e "  ${GREEN}Copied $pkg/ (imported by main.py)${NC}"
    fi
done

# Copy bin/monitoring if main.py imports from it
if grep -q "from bin" "$DEPLOY_DIR/main.py" 2>/dev/null || grep -q "import bin" "$DEPLOY_DIR/main.py" 2>/dev/null; then
    if [ -d "bin/monitoring" ]; then
        mkdir -p "$DEPLOY_DIR/bin"
        rsync -aL \
            --exclude='__pycache__' \
            --exclude='*.pyc' \
            "bin/monitoring/" "$DEPLOY_DIR/bin/monitoring/"
        echo -e "  ${GREEN}Copied bin/monitoring/ (imported by main.py)${NC}"
    fi
fi

# Ensure __init__.py exists in all package directories
find "$DEPLOY_DIR" -type d -exec touch {}/__init__.py \;

if [ "$VERBOSE" = true ]; then
    echo ""
    echo -e "  ${YELLOW}Deploy package contents:${NC}"
    find "$DEPLOY_DIR" -maxdepth 2 -type f | sort | head -40 | sed 's|^|    |'
    TOTAL_FILES=$(find "$DEPLOY_DIR" -type f | wc -l)
    echo "    ... ($TOTAL_FILES total files)"
fi

echo ""

# ============================================================================
# Step 2: Validate imports (catch ModuleNotFoundError before deploy)
# ============================================================================

echo -e "${BLUE}[2/4] Validating imports...${NC}"

if [ "$DRY_RUN" = true ]; then
    echo -e "  ${YELLOW}[DRY RUN] Skipping import validation${NC}"
else
    VALIDATE_RESULT=$(cd "$DEPLOY_DIR" && python3 -c "
import sys, importlib
sys.path.insert(0, '.')
try:
    importlib.import_module('main')
    print('PASS')
except Exception as e:
    print(f'FAIL: {e}')
    sys.exit(1)
" 2>&1) || true

    if echo "$VALIDATE_RESULT" | grep -q "^PASS"; then
        echo -e "  ${GREEN}Import validation passed${NC}"
    else
        echo -e "  ${YELLOW}WARNING: Import validation could not fully verify (may need GCP libs):${NC}"
        echo -e "  ${YELLOW}  $VALIDATE_RESULT${NC}"
        echo -e "  ${YELLOW}  Proceeding anyway (Cloud Build will catch real import errors)${NC}"
    fi
fi

echo ""

# ============================================================================
# Step 3: Deploy
# ============================================================================

echo -e "${BLUE}[3/4] Deploying Cloud Function...${NC}"
echo ""

# Build trigger arguments
TRIGGER_ARGS=""
if [ "$TRIGGER_TYPE" = "http" ]; then
    if [ "$ALLOW_UNAUTHENTICATED" = true ]; then
        TRIGGER_ARGS="--trigger-http --allow-unauthenticated"
    else
        TRIGGER_ARGS="--trigger-http --no-allow-unauthenticated"
    fi
elif [ "$TRIGGER_TYPE" = "topic" ]; then
    if [ -z "$TRIGGER_TOPIC" ]; then
        echo -e "${RED}ERROR: Pub/Sub trigger type requires a topic. Use --trigger-topic.${NC}"
        exit 1
    fi
    TRIGGER_ARGS="--trigger-topic $TRIGGER_TOPIC"
fi

# Build the deploy command
DEPLOY_CMD="gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime $RUNTIME \
    --region $REGION \
    --source $DEPLOY_DIR \
    --entry-point $ENTRY_POINT \
    $TRIGGER_ARGS \
    --service-account=$SERVICE_ACCOUNT \
    --update-env-vars GCP_PROJECT=$PROJECT,BUILD_COMMIT=$BUILD_COMMIT,BUILD_TIMESTAMP=$BUILD_TIMESTAMP \
    --update-labels commit-sha=$BUILD_COMMIT \
    --memory $MEMORY \
    --timeout $TIMEOUT \
    --max-instances $MAX_INSTANCES \
    --min-instances $MIN_INSTANCES \
    --project $PROJECT"

if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}[DRY RUN] Would execute:${NC}"
    echo ""
    echo "  $DEPLOY_CMD" | tr -s ' '
    echo ""
    echo -e "${YELLOW}[DRY RUN] Deploy package at: $DEPLOY_DIR${NC}"
    echo -e "${YELLOW}[DRY RUN] (temp dir will be cleaned up on exit)${NC}"
    echo ""

    # In dry-run, also show the IAM command that would run
    if [ "$SKIP_IAM" = false ] && [ "$TRIGGER_TYPE" = "topic" ]; then
        echo -e "${YELLOW}[DRY RUN] Would set IAM binding:${NC}"
        echo "  gcloud run services add-iam-policy-binding $FUNCTION_NAME \\"
        echo "    --region=$REGION \\"
        echo "    --member=serviceAccount:$PUBSUB_INVOKER_SA \\"
        echo "    --role=roles/run.invoker \\"
        echo "    --project=$PROJECT"
        echo ""
    fi

    echo -e "${GREEN}==================================================${NC}"
    echo -e "${GREEN}  DRY RUN COMPLETE - No changes made${NC}"
    echo -e "${GREEN}==================================================${NC}"
    exit 0
fi

# Execute the deploy
eval "$DEPLOY_CMD"

echo ""
echo -e "  ${GREEN}Cloud Function deployed successfully${NC}"
echo ""

# ============================================================================
# Step 4: Post-deploy (IAM binding for Pub/Sub functions)
# ============================================================================

echo -e "${BLUE}[4/4] Post-deployment tasks...${NC}"

# Pub/Sub triggered functions need IAM binding for the invoker service account
# (Session 205: Without this, Pub/Sub cannot deliver messages to the function)
if [ "$SKIP_IAM" = false ] && [ "$TRIGGER_TYPE" = "topic" ]; then
    echo ""
    echo -e "  ${YELLOW}Setting IAM binding for Pub/Sub invocation...${NC}"

    gcloud run services add-iam-policy-binding "$FUNCTION_NAME" \
        --region="$REGION" \
        --member="serviceAccount:$PUBSUB_INVOKER_SA" \
        --role="roles/run.invoker" \
        --project="$PROJECT" \
        --quiet 2>/dev/null

    # Verify the binding
    IAM_POLICY=$(gcloud run services get-iam-policy "$FUNCTION_NAME" \
        --region="$REGION" \
        --project="$PROJECT" \
        --format=json 2>/dev/null)

    if echo "$IAM_POLICY" | grep -q "roles/run.invoker"; then
        echo -e "  ${GREEN}IAM binding verified (roles/run.invoker)${NC}"
    else
        echo -e "  ${RED}WARNING: IAM binding verification failed${NC}"
        echo -e "  ${RED}Pub/Sub may not be able to invoke the function.${NC}"
        echo -e "  ${RED}Run manually: gcloud run services add-iam-policy-binding $FUNCTION_NAME --region=$REGION --member=serviceAccount:$PUBSUB_INVOKER_SA --role=roles/run.invoker --project=$PROJECT${NC}"
    fi
fi

# Display function details
echo ""
echo -e "${YELLOW}Function details:${NC}"
gcloud functions describe "$FUNCTION_NAME" \
    --region "$REGION" \
    --gen2 \
    --project "$PROJECT" \
    --format="table(name,state,updateTime)" 2>/dev/null || true

echo ""

# ============================================================================
# Summary
# ============================================================================

echo -e "${GREEN}==================================================${NC}"
echo -e "${GREEN}  DEPLOYMENT COMPLETE${NC}"
echo -e "${GREEN}==================================================${NC}"
echo ""
echo "  Function:     $FUNCTION_NAME"
echo "  Entry point:  $ENTRY_POINT"
echo "  Trigger:      $TRIGGER_TYPE"
if [ "$TRIGGER_TYPE" = "topic" ]; then
    echo "  Topic:        $TRIGGER_TOPIC"
fi
echo "  Commit:       $BUILD_COMMIT"
echo "  Memory:       $MEMORY"
echo "  Timeout:      $TIMEOUT"
echo ""
echo -e "${YELLOW}Useful commands:${NC}"
echo "  View logs:"
echo "    gcloud functions logs read $FUNCTION_NAME --region $REGION --limit 50"
echo ""
if [ "$TRIGGER_TYPE" = "http" ]; then
    FUNC_URL=$(gcloud functions describe "$FUNCTION_NAME" \
        --region="$REGION" --gen2 --project="$PROJECT" \
        --format="value(serviceConfig.uri)" 2>/dev/null || echo "")
    if [ -n "$FUNC_URL" ]; then
        echo "  Function URL: $FUNC_URL"
        echo "  Test: curl '$FUNC_URL'"
    fi
elif [ "$TRIGGER_TYPE" = "topic" ]; then
    echo "  Trigger manually:"
    echo "    gcloud pubsub topics publish $TRIGGER_TOPIC --message='{\"trigger_source\": \"manual\"}'"
fi
echo ""
echo -e "${GREEN}Done.${NC}"
