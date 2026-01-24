#!/bin/bash
set -euo pipefail

# Setup script for NBA Analytics infrastructure
# Run this once per GCP project

PROJECT_ID=$(gcloud config get-value project)
REGION="us-west2"

echo "🏗️ Setting up NBA Analytics infrastructure..."
echo "📦 Project: $PROJECT_ID"
echo "🌎 Region: $REGION"

# Check if repository already exists
if gcloud artifacts repositories describe pipeline --location=$REGION &>/dev/null; then
    echo "✅ Artifact Registry repository 'pipeline' already exists"
else
    echo "🔨 Creating Artifact Registry repository..."
    gcloud artifacts repositories create pipeline \
        --repository-format=docker \
        --location=$REGION \
        --description="NBA Analytics Docker images"
    echo "✅ Repository created"
fi

# Verify setup
echo "🔍 Verifying setup..."
gcloud artifacts repositories list --location=$REGION

echo ""
echo "✅ Infrastructure setup complete!"
echo "🎯 Next steps:"
echo "   1. Run: make setup-sophisticated"
echo "   2. Consider adding infra/artifact_registry.tf for IaC"
echo ""
echo "📋 Repository URL:"
echo "   ${REGION}-docker.pkg.dev/${PROJECT_ID}/pipeline/"
