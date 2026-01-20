#!/bin/bash
#
# Run Smoke Tests in CI/CD Pipeline
#
# Usage: ./bin/ci/run_smoke_tests.sh [--environment staging|production]

set -euo pipefail

ENVIRONMENT="${ENVIRONMENT:-staging}"

echo "Running smoke tests for environment: $ENVIRONMENT"

# Set environment variables for tests
export ENVIRONMENT="$ENVIRONMENT"

# Run smoke tests
pytest tests/smoke/test_health_endpoints.py \
  -v \
  --tb=short \
  --junit-xml=test-results/smoke-tests.xml \
  --html=test-results/smoke-tests.html

exit_code=$?

if [ $exit_code -eq 0 ]; then
  echo "✅ All smoke tests passed"
else
  echo "❌ Smoke tests failed"
  exit $exit_code
fi
