#!/bin/bash
#
# Sport Configuration for Shell Scripts
# =====================================
# Source this file at the top of any script that needs sport-specific config.
#
# Usage:
#   source "$(dirname "$0")/../common/sport_config.sh"
#   # or with absolute path:
#   source /home/naji/code/nba-stats-scraper/bin/common/sport_config.sh
#
# Then use variables like:
#   - $PROJECT_ID
#   - $GCS_BUCKET
#   - $RAW_DATASET
#   - $ANALYTICS_DATASET
#   - etc.
#
# Environment Variable:
#   SPORT: Set to 'nba' or 'mlb' (defaults to 'nba')
#
# Created: 2026-01-06

# Get sport from environment (default: nba)
SPORT=${SPORT:-nba}

# Validate sport
case "$SPORT" in
    nba|mlb)
        ;;
    *)
        echo "ERROR: Invalid SPORT value: $SPORT (must be 'nba' or 'mlb')"
        exit 1
        ;;
esac

# GCP Project (same for all sports currently)
PROJECT_ID="nba-props-platform"

# GCS Bucket (sport-specific)
GCS_BUCKET="${SPORT}-scraped-data"

# BigQuery Datasets (sport-specific)
RAW_DATASET="${SPORT}_raw"
ANALYTICS_DATASET="${SPORT}_analytics"
PRECOMPUTE_DATASET="${SPORT}_precompute"
PREDICTIONS_DATASET="${SPORT}_predictions"
REFERENCE_DATASET="${SPORT}_reference"
ORCHESTRATION_DATASET="${SPORT}_orchestration"

# Pub/Sub Topic prefix
TOPIC_PREFIX="${SPORT}"

# Cloud Run region
REGION="us-west2"

# Helper function to get full topic name
get_topic() {
    local phase="$1"
    echo "${TOPIC_PREFIX}-${phase}"
}

# Export all variables
export SPORT
export PROJECT_ID
export GCS_BUCKET
export RAW_DATASET
export ANALYTICS_DATASET
export PRECOMPUTE_DATASET
export PREDICTIONS_DATASET
export REFERENCE_DATASET
export ORCHESTRATION_DATASET
export TOPIC_PREFIX
export REGION

# Print config if DEBUG=true
if [ "${DEBUG:-false}" = "true" ]; then
    echo "=== Sport Configuration ==="
    echo "SPORT:               $SPORT"
    echo "PROJECT_ID:          $PROJECT_ID"
    echo "GCS_BUCKET:          $GCS_BUCKET"
    echo "RAW_DATASET:         $RAW_DATASET"
    echo "ANALYTICS_DATASET:   $ANALYTICS_DATASET"
    echo "PRECOMPUTE_DATASET:  $PRECOMPUTE_DATASET"
    echo "PREDICTIONS_DATASET: $PREDICTIONS_DATASET"
    echo "ORCHESTRATION_DATASET: $ORCHESTRATION_DATASET"
    echo "TOPIC_PREFIX:        $TOPIC_PREFIX"
    echo "==========================="
fi
