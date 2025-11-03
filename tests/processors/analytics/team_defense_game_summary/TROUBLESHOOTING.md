# Path: tests/processors/analytics/team_defense_game_summary/TROUBLESHOOTING.md

# Troubleshooting Test Setup Issues

## Common Issues and Solutions

### Issue 1: ModuleNotFoundError for Google modules

**Symptom:**
```
ModuleNotFoundError: No module named 'google.auth'
ModuleNotFoundError: No module named 'google.cloud.exceptions'
```

**Solution:**
The `conftest.py` file MUST be in the same directory as your test files and must be imported FIRST before any test imports.

**Verify:**
```bash
# Check conftest.py exists
ls -la conftest.py

# Check it's being loaded
pytest --fixtures | grep "conftest"
```

**If still failing:**
1. Delete all `__pycache__` directories:
   ```bash
   find . -type d -name __pycache__ -exec rm -rf {} +
   ```

2. Delete `.pytest_cache`:
   ```bash
   rm -rf .pytest_cache
   ```

3. Try running from the test directory:
   ```bash
   cd tests/processors/analytics/team_defense_game_summary
   pytest test_unit.py -v
   ```

---

### Issue 2: Import path issues

**Symptom:**
```
ImportError: cannot import name 'TeamDefenseGameSummaryProcessor'
ModuleNotFoundError: No module named 'data_processors'
```

**Solution:**
Run tests from the project root, not from the test directory.

**Correct:**
```bash
# From project root
cd ~/code/nba-stats-scraper
python tests/processors/analytics/team_defense_game_summary/run_tests.py unit
```

**Wrong:**
```bash
# From test directory (breaks imports)
cd tests/processors/analytics/team_defense_game_summary
pytest test_unit.py
```

---

### Issue 3: Fixture not found

**Symptom:**
```
fixture 'mock_processor' not found
fixture 'sample_raw_extracted_data' not found
```

**Solution:**
Ensure `conftest.py` is in the correct directory and pytest can see it.

**Debug:**
```bash
pytest --fixtures test_unit.py
```

Should show:
- `mock_processor`
- `sample_raw_extracted_data`
- `dependency_check_result_success`
- etc.

---

### Issue 4: Google Cloud SDK is installed but tests fail

**Symptom:**
```
google.auth.exceptions.DefaultCredentialsError: Could not automatically determine credentials
```

**Solution:**
The mocking isn't working because real Google Cloud SDK is being imported first.

**Fix:**
Move Google Cloud imports in your code to be lazy imports (inside functions), or ensure conftest.py runs first:

```bash
# Force conftest to load first
PYTHONPATH=. pytest test_unit.py --import-mode=importlib
```

---

### Issue 5: Tests pass individually but fail together

**Symptom:**
```bash
pytest test_unit.py::TestClassName::test_method  # PASSES
pytest test_unit.py  # FAILS
```

**Solution:**
Fixture scope issue or mock state pollution.

**Fix:**
1. Check fixture scopes in conftest.py
2. Ensure mocks are reset between tests:
   ```python
   @pytest.fixture(autouse=True)
   def reset_mocks():
       yield
       # Reset any global state here
   ```

---

### Issue 6: Coverage command fails

**Symptom:**
```
pytest: error: unrecognized arguments: --cov
```

**Solution:**
Install pytest-cov:
```bash
pip install pytest-cov
```

---

## Verification Checklist

Before running tests, verify:

- [ ] `conftest.py` exists in test directory
- [ ] Running from project root directory
- [ ] No `__pycache__` directories interfering
- [ ] pytest and pytest-cov installed
- [ ] Python path includes project root

## Quick Test

Run this minimal test to verify mocking works:

```python
# test_mock_verify.py
def test_google_cloud_mocked():
    """Verify Google Cloud is mocked."""
    import sys
    assert 'google.cloud' in sys.modules
    assert 'google.auth' in sys.modules
    
    from google.cloud import bigquery
    from google.auth import default
    
    # Should not raise - modules are mocked
    assert bigquery is not None
    assert default is not None
```

Run it:
```bash
pytest test_mock_verify.py -v
```

If this passes, your mocking setup is correct.

---

## Still Having Issues?

### Method 1: Install Google Cloud SDK (not recommended for tests)

```bash
pip install google-cloud-bigquery google-cloud-storage google-auth
```

**Downside:** Tests will be slow and may try to connect to real GCP.

### Method 2: Use pytest import mode

```bash
pytest test_unit.py --import-mode=importlib
```

### Method 3: Set PYTHONPATH explicitly

```bash
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
pytest tests/processors/analytics/team_defense_game_summary/test_unit.py -v
```

### Method 4: Debug import order

Add this to the TOP of test_unit.py:

```python
import sys
print("=== LOADED MODULES ===")
for mod in sorted(sys.modules.keys()):
    if 'google' in mod:
        print(f"  {mod}")
print("======================")
```

This will show you which Google modules are loaded and whether they're mocked.

---

## Contact

If none of these solutions work, check:
1. Python version (should be 3.12.3)
2. Virtual environment is activated
3. All dependencies installed: `pip install -r requirements.txt`
4. Project structure matches expected layout

## Expected Directory Structure

```
nba-stats-scraper/
├── data_processors/
│   └── analytics/
│       └── team_defense_game_summary/
│           └── team_defense_game_summary_processor.py
├── tests/
│   └── processors/
│       └── analytics/
│           └── team_defense_game_summary/
│               ├── conftest.py          ← MUST exist
│               ├── test_unit.py
│               ├── test_integration.py
│               ├── test_validation.py
│               ├── run_tests.py
│               ├── README.md
│               └── TROUBLESHOOTING.md   ← This file
└── shared/
    └── utils/
        ├── bigquery_client.py
        └── notification_system.py
```