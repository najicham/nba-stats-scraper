#!/bin/bash
#
# check_dockerfile_dependencies.sh
#
# Validates that all Python module dependencies are included in Dockerfiles
#
# This prevents incidents like:
# - Session 101: Worker missing predictions/shared/
# - Session 102: Coordinator missing distributed_lock.py
#
# Usage:
#   ./bin/validation/check_dockerfile_dependencies.sh
#
# Exit codes:
#   0 = All dependencies satisfied
#   1 = Missing dependencies found

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "🔍 Dockerfile Dependency Checker"
echo "================================="
echo ""

ERRORS=0

# Function to check if a module is copied in Dockerfile
check_dockerfile_has_module() {
    local dockerfile="$1"
    local module_path="$2"
    local module_name=$(basename "$module_path" .py)

    if ! grep -q "COPY.*${module_path}" "$dockerfile" 2>/dev/null; then
        return 1
    fi
    return 0
}

# Function to extract Python imports from a file
extract_local_imports() {
    local python_file="$1"
    # Extract 'from X import' and 'import X' statements (non-stdlib only)
    grep -oP '(?<=^from |^import )\w+' "$python_file" 2>/dev/null || true
}

# Function to check if import is a local module
is_local_module() {
    local module="$1"
    local search_dirs=("predictions/worker" "predictions/coordinator" "predictions/shared")

    for dir in "${search_dirs[@]}"; do
        if [ -f "$PROJECT_ROOT/$dir/${module}.py" ]; then
            echo "$dir/${module}.py"
            return 0
        fi
    done
    return 1
}

echo "Checking: Prediction Coordinator"
echo "---------------------------------"

COORDINATOR_FILE="$PROJECT_ROOT/predictions/coordinator/coordinator.py"
COORDINATOR_DOCKERFILE="$PROJECT_ROOT/docker/predictions-coordinator.Dockerfile"

if [ ! -f "$COORDINATOR_FILE" ]; then
    echo "❌ coordinator.py not found"
    exit 1
fi

if [ ! -f "$COORDINATOR_DOCKERFILE" ]; then
    echo "❌ Dockerfile not found"
    exit 1
fi

# Check coordinator.py imports
COORDINATOR_MISSING=()

echo "Analyzing coordinator.py imports..."
while IFS= read -r import_name; do
    # Skip common stdlib modules
    case "$import_name" in
        os|sys|json|time|datetime|logging|re|pathlib|typing|collections|functools)
            continue
            ;;
    esac

    # Check if it's a local module
    if module_path=$(is_local_module "$import_name"); then
        # Check if it's in the Dockerfile
        if ! check_dockerfile_has_module "$COORDINATOR_DOCKERFILE" "$module_path"; then
            COORDINATOR_MISSING+=("$module_path")
        fi
    fi
done < <(extract_local_imports "$COORDINATOR_FILE")

# Check batch_staging_writer.py dependencies (it's imported by coordinator)
BATCH_WRITER_FILE="$PROJECT_ROOT/predictions/worker/batch_staging_writer.py"
if [ -f "$BATCH_WRITER_FILE" ]; then
    echo "Analyzing batch_staging_writer.py transitive dependencies..."
    while IFS= read -r import_name; do
        case "$import_name" in
            os|sys|json|time|datetime|logging|re|pathlib|typing|collections|functools)
                continue
                ;;
        esac

        if module_path=$(is_local_module "$import_name"); then
            if ! check_dockerfile_has_module "$COORDINATOR_DOCKERFILE" "$module_path"; then
                # Check if already in missing list
                if [[ ! " ${COORDINATOR_MISSING[@]} " =~ " ${module_path} " ]]; then
                    COORDINATOR_MISSING+=("$module_path (transitive from batch_staging_writer)")
                fi
            fi
        fi
    done < <(extract_local_imports "$BATCH_WRITER_FILE")
fi

# Report results
if [ ${#COORDINATOR_MISSING[@]} -eq 0 ]; then
    echo "✅ All coordinator dependencies satisfied"
else
    echo "❌ Missing dependencies in Dockerfile:"
    printf '   - %s\n' "${COORDINATOR_MISSING[@]}"
    echo ""
    echo "Fix: Add to $COORDINATOR_DOCKERFILE:"
    for dep in "${COORDINATOR_MISSING[@]}"; do
        echo "  COPY $dep /app/$(basename $dep)"
    done
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "Checking: Prediction Worker"
echo "---------------------------"

WORKER_FILE="$PROJECT_ROOT/predictions/worker/worker.py"
WORKER_DOCKERFILE="$PROJECT_ROOT/predictions/worker/Dockerfile"

if [ ! -f "$WORKER_FILE" ]; then
    echo "⚠️  worker.py not found (skipping)"
elif [ ! -f "$WORKER_DOCKERFILE" ]; then
    echo "⚠️  Worker Dockerfile not found (skipping)"
else
    WORKER_MISSING=()

    echo "Analyzing worker.py imports..."
    while IFS= read -r import_name; do
        case "$import_name" in
            os|sys|json|time|datetime|logging|re|pathlib|typing|collections|functools|numpy|pandas)
                continue
                ;;
        esac

        if module_path=$(is_local_module "$import_name"); then
            if ! check_dockerfile_has_module "$WORKER_DOCKERFILE" "$module_path"; then
                WORKER_MISSING+=("$module_path")
            fi
        fi
    done < <(extract_local_imports "$WORKER_FILE")

    if [ ${#WORKER_MISSING[@]} -eq 0 ]; then
        echo "✅ All worker dependencies satisfied"
    else
        echo "❌ Missing dependencies in Dockerfile:"
        printf '   - %s\n' "${WORKER_MISSING[@]}"
        echo ""
        echo "Fix: Add to $WORKER_DOCKERFILE:"
        for dep in "${WORKER_MISSING[@]}"; do
            echo "  COPY $dep /app/$(basename $dep)"
        done
        ERRORS=$((ERRORS + 1))
    fi
fi

echo ""
echo "================================="
if [ $ERRORS -eq 0 ]; then
    echo "✅ All Dockerfile dependencies validated"
    exit 0
else
    echo "❌ Found $ERRORS Dockerfile(s) with missing dependencies"
    echo ""
    echo "This check prevents incidents like:"
    echo "  - Session 101: Worker missing predictions/shared/"
    echo "  - Session 102: Coordinator missing distributed_lock.py"
    echo ""
    echo "Please fix the Dockerfiles before deploying."
    exit 1
fi
