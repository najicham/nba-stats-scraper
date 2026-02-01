# Session 61 Start Prompt

**Copy this prompt to start the next session:**

---

Continue from Session 60. Quick context:

**Session 60 Status (Feb 1, 2026)**:
✅ Fixed phase3-to-phase4-orchestrator deployment failure
✅ Deployed revision 00027 - HEALTHY and ACTIVE
✅ Updated all 4 orchestrator deployment scripts
✅ Updated troubleshooting and consolidation documentation
✅ All fixes committed (3 commits) - **READY TO PUSH**

**Current Status**:
- Orchestrator running successfully on revision 00027
- Firestore completion tracking restored (last update: Jan 30, 5/5 processors)
- 85+ commits ready to push to origin
- System healthy and operational

---

## Your Mission - Start Here

### Priority 1: Push Commits and Verify System Health

**1.1 Push commits to origin**
```bash
git push
```

**1.2 Verify Feb 1 data processing**
Run daily validation to check if overnight processing completed:
```bash
/validate-daily
```

Expected outcome:
- Feb 1 games processed by Phase 3 processors
- Firestore shows 5/5 processors complete for Feb 1
- Phase 4 auto-triggered successfully
- Predictions generated for upcoming games

**1.3 Check orchestrator activity**
Verify the orchestrator processed Feb 1 completion messages:
```bash
python3 << 'EOF'
from google.cloud import firestore
db = firestore.Client()

# Check Feb 1 completion
doc = db.collection('phase3_completion').document('2026-02-01').get()
if doc.exists:
    data = doc.to_dict()
    completed = [k for k in data.keys() if not k.startswith('_')]
    print(f"✅ Feb 1: {len(completed)}/5 processors complete")
    print(f"   Triggered: {data.get('_triggered', False)}")
    print(f"   Last updated: {data.get('_last_updated') or data.get('_last_update')}")
    print(f"   Processors: {completed}")
else:
    print("⚠️  No Feb 1 completion record yet")
    print("   This is expected if games haven't finished or Phase 3 hasn't run")
EOF
```

**1.4 Check orchestrator logs**
Look for recent message processing:
```bash
gcloud logging read 'resource.labels.service_name="phase3-to-phase4-orchestrator"
  AND jsonPayload.message=~"Processing|completion|trigger"
  AND timestamp>=2026-02-01T00:00:00Z' \
  --limit=20 --format=json | jq -r '.[] | "\(.timestamp) \(.jsonPayload.message)"'
```

---

### Priority 2: Implement Future Work (Choose Based on Time)

Session 60 identified several improvements. Choose what to tackle based on available time:

#### P2-A: Add Pre-deployment Import Validation (30 minutes)

**Why**: Catch missing modules BEFORE deployment fails in production

**Task**: Create validation script that checks if all imports in main.py exist in build directory

**Steps**:

1. Create script `bin/validation/check_cloud_function_imports.py`:
```python
#!/usr/bin/env python3
"""
Pre-deployment import validation for Cloud Functions.

Extracts imports from main.py and verifies all imported modules
exist in the build directory before deploying to Cloud Functions.

Usage:
    python bin/validation/check_cloud_function_imports.py /path/to/build/dir /path/to/main.py
"""

import sys
import ast
import os
from pathlib import Path

def extract_imports(main_py_path):
    """Extract all 'from X import Y' statements from main.py."""
    with open(main_py_path) as f:
        tree = ast.parse(f.read())

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports

def check_module_exists(build_dir, module_name):
    """Check if a module exists in the build directory."""
    # Convert module.name to path: shared.utils.foo -> shared/utils/foo.py
    parts = module_name.split('.')

    # Check for package (directory with __init__.py)
    package_path = Path(build_dir) / '/'.join(parts)
    if package_path.is_dir() and (package_path / '__init__.py').exists():
        return True

    # Check for module file
    module_path = Path(build_dir) / '/'.join(parts[:-1]) / f"{parts[-1]}.py"
    if module_path.exists():
        return True

    return False

def main(build_dir, main_py_path):
    imports = extract_imports(main_py_path)

    print(f"Checking {len(imports)} imports in {main_py_path}...")

    missing = []
    for imp in imports:
        if not check_module_exists(build_dir, imp):
            missing.append(imp)

    if missing:
        print(f"❌ FAILED: {len(missing)} missing modules:")
        for m in missing:
            print(f"   - {m}")
        return 1
    else:
        print(f"✅ PASSED: All {len(imports)} imports found in build directory")
        return 0

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: check_cloud_function_imports.py BUILD_DIR MAIN_PY")
        sys.exit(1)
    sys.exit(main(sys.argv[1], sys.argv[2]))
```

2. Make it executable:
```bash
chmod +x bin/validation/check_cloud_function_imports.py
```

3. Add to deployment script (e.g., `deploy_phase3_to_phase4.sh`) after build directory is created:
```bash
# After rsync commands that create $BUILD_DIR

# Validate imports before deployment
echo -e "${YELLOW}Validating imports in build directory...${NC}"
if python bin/validation/check_cloud_function_imports.py "$BUILD_DIR" "$SOURCE_DIR/main.py"; then
    echo -e "${GREEN}✓ All imports validated${NC}"
else
    echo -e "${RED}✗ Import validation failed - missing modules in build directory${NC}"
    exit 1
fi
```

4. Test with phase3-to-phase4 deployment:
```bash
# Dry run - test validation script
./bin/orchestrators/deploy_phase3_to_phase4.sh
# Should pass validation step
```

5. Apply to all 4 orchestrator deployment scripts

**Commit**:
```bash
git add bin/validation/check_cloud_function_imports.py
git add bin/orchestrators/deploy_*.sh
git commit -m "feat: Add pre-deployment import validation for Cloud Functions

Prevents deployment failures due to missing modules in package.

- Extracts imports from main.py using AST parsing
- Verifies all imported modules exist in build directory
- Fails deployment early if modules missing
- Applied to all 4 orchestrator deployment scripts

Prevention for: Session 60 orchestrator failure (missing shared.validation module)

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

#### P2-B: Verify Other Orchestrators Deploy Successfully (15 minutes)

**Why**: Ensure deployment script fixes work for all orchestrators, not just phase3-to-phase4

**Task**: Test deployment of other 3 orchestrators

**Steps**:

1. Check current deployment status:
```bash
for func in phase2-to-phase3 phase4-to-phase5 phase5-to-phase6; do
    echo "=== $func ==="
    gcloud run services describe "$func-orchestrator" --region=us-west2 \
      --format="value(status.conditions[0].status,metadata.annotations['run.googleapis.com/launchStage'])" 2>&1 | head -2
    echo
done
```

2. Deploy each orchestrator (one at a time):
```bash
# Phase 2 → 3
./bin/orchestrators/deploy_phase2_to_phase3.sh

# Phase 4 → 5
./bin/orchestrators/deploy_phase4_to_phase5.sh

# Phase 5 → 6
./bin/orchestrators/deploy_phase5_to_phase6.sh
```

3. Verify each deployment:
```bash
# Check health for each
gcloud run services describe phase2-to-phase3-orchestrator --region=us-west2 \
  --format="value(status.conditions[0])"

gcloud run services describe phase4-to-phase5-orchestrator --region=us-west2 \
  --format="value(status.conditions[0])"

gcloud run services describe phase5-to-phase6-orchestrator --region=us-west2 \
  --format="value(status.conditions[0])"
```

4. Document results in handoff

**Expected outcome**: All 3 orchestrators deploy successfully with healthy revisions

---

#### P2-C: Update Consolidation Documentation (10 minutes)

**Why**: Prevent future developers from making the same mistake

**Task**: Add "Deployment Checklist" section to consolidation doc

**Steps**:

1. Edit `docs/architecture/cloud-function-shared-consolidation.md`

2. Add new section after "Risks and Mitigations":

```markdown
## Deployment Checklist for Future Consolidations

**CRITICAL**: When moving or deleting shared directories, follow this checklist to prevent deployment failures.

### Before Consolidation

- [ ] List all Cloud Functions that import from the directory being moved/deleted:
  ```bash
  grep -r "from orchestration.shared" orchestration/cloud_functions/*/main.py
  grep -r "from shared.OLD_DIR" orchestration/cloud_functions/*/main.py
  ```

- [ ] List all deployment scripts:
  ```bash
  ls bin/orchestrators/deploy_*.sh
  ```

- [ ] Check which deployment scripts reference the directory:
  ```bash
  grep -l "orchestration/shared" bin/orchestrators/deploy_*.sh
  grep -l "shared/OLD_DIR" bin/orchestrators/deploy_*.sh
  ```

### During Consolidation

- [ ] Update all import statements in Cloud Function code
- [ ] Update all deployment scripts to copy new directory structure
- [ ] Remove references to deleted directories from deployment scripts
- [ ] Update symlinks in `orchestration/cloud_functions/*/shared/`

### After Consolidation

- [ ] Test deployment of EACH affected Cloud Function:
  ```bash
  for script in bin/orchestrators/deploy_*.sh; do
      echo "Testing $script..."
      $script || echo "FAILED: $script"
  done
  ```

- [ ] Verify health of deployed functions:
  ```bash
  gcloud run services list --filter="metadata.name:orchestrator" \
    --format="table(metadata.name,status.conditions[0].status)"
  ```

- [ ] Check for broken symlinks:
  ```bash
  find orchestration/cloud_functions -type l ! -exec test -e {} \; -print
  ```

### Incident Prevention

**Historical Incidents**:
- **Jan 30, 2026**: Deleted `orchestration/shared/` without updating deployment scripts
  - Result: 4 orchestrators failed to deploy on Jan 29-30
  - Fix: Session 60 updated all deployment scripts
  - Prevention: This checklist

**Key Learning**: Always test deployments after structural changes, even if code changes look correct.
```

3. Commit:
```bash
git add docs/architecture/cloud-function-shared-consolidation.md
git commit -m "docs: Add deployment checklist for future consolidations

Prevents deployment failures when moving/deleting shared directories.

Includes:
- Pre-consolidation checks (find affected functions/scripts)
- During consolidation updates (imports, scripts, symlinks)
- Post-consolidation verification (test all deployments)
- Historical incident reference (Jan 30, 2026)

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

#### P3-A: Create GitHub Issues for Long-term Work (15 minutes)

**Why**: Track improvements for future sessions

**Task**: Create issues for automated testing and safeguards

**Issue 1: Automated Cloud Function Deployment Testing**

Title: `Add automated Cloud Function deployment testing to CI/CD`

Body:
```markdown
## Problem

Cloud Functions can fail to deploy due to missing dependencies, import errors, or configuration issues. These failures are only caught when deploying to production, causing outages.

**Recent Incident**: Session 60 (Feb 1, 2026) - orchestrator failed to deploy due to missing shared modules after Jan 30 consolidation.

## Proposed Solution

Add GitHub Actions workflow to test Cloud Function deployments on every PR.

### Implementation

1. **Create test GCP project** for deployment testing
   - Separate from production to avoid impacting live services
   - Use service account with limited permissions

2. **Add GitHub Actions workflow** (`.github/workflows/test-cloud-functions.yml`):
   ```yaml
   name: Test Cloud Function Deployments

   on:
     pull_request:
       paths:
         - 'orchestration/cloud_functions/**'
         - 'bin/orchestrators/deploy_*.sh'
         - 'shared/**'

   jobs:
     test-deployments:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v3
         - uses: google-github-actions/auth@v1
           with:
             credentials_json: ${{ secrets.GCP_TEST_SA_KEY }}
         - name: Deploy to test project
           run: |
             for script in bin/orchestrators/deploy_*.sh; do
               echo "Testing $script..."
               # Modify script to deploy to test project
               PROJECT_ID=nba-props-test $script
             done
         - name: Verify health
           run: |
             gcloud run services list --project=nba-props-test \
               --filter="metadata.name:orchestrator" \
               --format="value(status.conditions[0].status)"
   ```

3. **Deployment script changes**:
   - Make PROJECT_ID configurable via environment variable
   - Add `--dry-run` flag to deployment scripts for testing

### Benefits

- Catch deployment failures before production
- Test consolidations and refactorings safely
- Reduce MTTR (mean time to recovery)

### Estimated Effort

- Setup test project: 1 hour
- Create GitHub Actions workflow: 2 hours
- Modify deployment scripts: 1 hour
- Testing and documentation: 1 hour
- **Total**: ~5 hours

### Labels

`enhancement`, `ci-cd`, `reliability`, `orchestration`
```

**Issue 2: Add Consolidation Safeguards**

Title: `Add pre-commit hook to detect references to deleted directories`

Body:
```markdown
## Problem

When consolidating or refactoring shared directories, it's easy to miss references in deployment scripts, documentation, or config files. This causes failures days or weeks later.

**Recent Incident**: Session 60 (Feb 1, 2026) - deployment scripts still referenced deleted `orchestration/shared/` directory 2 days after it was removed.

## Proposed Solution

Add pre-commit hook that warns about references to known-deleted directories.

### Implementation

1. **Create `.deleted-paths.txt`** at repository root:
   ```
   orchestration/shared/utils
   orchestration/shared/config
   ```

2. **Add pre-commit hook** (`.pre-commit-hooks/check-deleted-paths.py`):
   ```python
   #!/usr/bin/env python3
   """Check for references to deleted/moved directories."""

   import sys
   import re
   from pathlib import Path

   # Load deleted paths
   deleted_paths = Path('.deleted-paths.txt').read_text().strip().split('\n')

   # Check staged files
   for file_path in sys.argv[1:]:
       if not Path(file_path).exists():
           continue

       content = Path(file_path).read_text()
       for deleted in deleted_paths:
           if deleted in content:
               print(f"⚠️  WARNING: {file_path} references deleted path: {deleted}")
               print(f"   This may cause deployment or runtime failures.")
               print(f"   Please update or verify this reference is intentional.")

   # Don't block commit, just warn
   sys.exit(0)
   ```

3. **Add to `.pre-commit-config.yaml`**:
   ```yaml
   - id: check-deleted-paths
     name: Check for deleted path references
     entry: python .pre-commit-hooks/check-deleted-paths.py
     language: system
     pass_filenames: true
   ```

### Benefits

- Early warning when refactoring
- Prevents deployment failures
- Low overhead (just warnings, doesn't block commits)

### Estimated Effort

- Create hook script: 30 minutes
- Add to pre-commit config: 10 minutes
- Test with various file types: 20 minutes
- Documentation: 10 minutes
- **Total**: ~70 minutes

### Labels

`enhancement`, `developer-experience`, `reliability`
```

**Create the issues**:
```bash
# Copy the markdown above into GitHub Issues UI, or use gh CLI:
gh issue create --title "Add automated Cloud Function deployment testing to CI/CD" \
  --body-file /tmp/issue1.md \
  --label enhancement,ci-cd,reliability,orchestration

gh issue create --title "Add pre-commit hook to detect references to deleted directories" \
  --body-file /tmp/issue2.md \
  --label enhancement,developer-experience,reliability
```

---

## Success Criteria

**Minimum for Session 61** (Must Do):
- ✅ All commits pushed to origin
- ✅ Feb 1 data validated (predictions generated, no missing data)
- ✅ Orchestrator Firestore shows 5/5 processors for Feb 1

**Good** (Should Do):
- ✅ Pre-deployment import validation added (P2-A)
- ✅ Other orchestrators deployed and verified (P2-B)

**Excellent** (Nice to Have):
- ✅ Consolidation checklist documented (P2-C)
- ✅ GitHub issues created for automation (P3-A)

---

## Quick Reference Commands

### Check System Health
```bash
# Daily validation
/validate-daily

# Check orchestrator status
gcloud run services list --filter="metadata.name:orchestrator" \
  --format="table(metadata.name,status.conditions[0].status,metadata.labels.revision)"

# Check Firestore completion for Feb 1
python3 -c "
from google.cloud import firestore
db = firestore.Client()
doc = db.collection('phase3_completion').document('2026-02-01').get()
print(f'Feb 1: {len([k for k in doc.to_dict().keys() if not k.startswith(\"_\")])}/5 processors' if doc.exists else 'No Feb 1 data yet')
"
```

### Deployment
```bash
# Deploy orchestrator
./bin/orchestrators/deploy_phase3_to_phase4.sh

# Check deployment logs
gcloud logging read 'resource.labels.service_name="phase3-to-phase4-orchestrator"' \
  --limit=20 --format="value(timestamp,severity,textPayload)"
```

### Git Operations
```bash
# Push commits
git push

# Check status
git status

# View recent commits
git log --oneline -5
```

---

## Context from Session 60

**What Was Fixed**:
- Root cause: Jan 30 consolidation deleted `orchestration/shared/` but deployment scripts still referenced it
- Fixed: Updated all 4 orchestrator deployment scripts to copy all shared modules (utils, clients, validation, config)
- Deployed: phase3-to-phase4-orchestrator revision 00027 is HEALTHY and ACTIVE
- Documented: Troubleshooting matrix and consolidation guide updated

**Key Files Changed**:
- `bin/orchestrators/deploy_phase2_to_phase3.sh`
- `bin/orchestrators/deploy_phase3_to_phase4.sh`
- `bin/orchestrators/deploy_phase4_to_phase5.sh`
- `bin/orchestrators/deploy_phase5_to_phase6.sh`
- `docs/09-handoff/2026-02-01-SESSION-60-HANDOFF.md`
- `docs/02-operations/troubleshooting-matrix.md`
- `docs/architecture/cloud-function-shared-consolidation.md`

**Commits** (ready to push):
- 718f2456: Fix orchestrator deployment scripts
- 83e4fe51: Add Session 60 handoff
- (latest): Add troubleshooting and consolidation notes

**Current Metrics**:
- Firestore last update: Jan 30, 5/5 processors
- Orchestrator revision: 00027-mug (HEALTHY)
- Pending commits: 85+

---

## Red Flags to Watch For

🚨 **If Firestore shows no Feb 1 completion by 8 AM PT**:
- Check if games finished (some late games end after midnight)
- Check Phase 3 processor logs for failures
- Verify orchestrator is receiving Pub/Sub messages

🚨 **If validation shows missing data for Feb 1**:
- Run spot checks on specific players
- Check if scrapers ran successfully
- Look for Phase 2 → Phase 3 orchestrator failures

🚨 **If orchestrator logs show import errors**:
- Deployment script may not have copied all modules
- Re-run deployment with verbose logging
- Check build directory has all shared/* subdirectories

---

## Files to Reference

- **Session 60 Handoff**: `docs/09-handoff/2026-02-01-SESSION-60-HANDOFF.md` (comprehensive details)
- **Troubleshooting**: `docs/02-operations/troubleshooting-matrix.md` (Section 6.4)
- **Consolidation Guide**: `docs/architecture/cloud-function-shared-consolidation.md`
- **Deployment Scripts**: `bin/orchestrators/deploy_*.sh`

---

**Ready to go!** Start with Priority 1 (push commits + validate Feb 1), then tackle Priority 2 items based on available time.

Good luck! 🚀
