# Cloud Run Jobs - Argument Parsing Guide

**Created:** 2025-11-21 18:35:00 PST
**Last Updated:** 2025-11-21 18:35:00 PST

Quick reference for passing arguments to Cloud Run jobs via `gcloud run jobs execute`.

---

## The Critical Issue

**Problem:** GCloud treats commas as argument separators, breaking comma-separated values.

```bash
# What you type:
--args="--seasons=2021,2022,2023"

# What gcloud parses:
ARG[0] = "--seasons=2021"
ARG[1] = "2022"          # Unexpected!
ARG[2] = "2023"          # Unexpected!

# Python sees:
sys.argv = ["script.py", "--seasons=2021", "2022", "2023"]

# Result:
error: unrecognized arguments: 2022 2023
```

---

## Solution: Custom Delimiter Syntax

**Use `^DELIMITER^` to change the argument separator:**

```bash
# Use pipe (|) as delimiter instead of comma
gcloud run jobs execute nbac-gamebook-backfill \
    --region=us-west2 \
    --args="^|^--seasons=2021,2022,2023|--limit=5"

# How it works:
# ARG[0] = "--seasons=2021,2022,2023"  ✅ Comma preserved!
# ARG[1] = "--limit=5"
```

**You can use any delimiter character:**
```bash
--args="^;^--seasons=2021,2022,2023;--limit=5"
--args="^#^--seasons=2021,2022,2023#--limit=5"
```

**Reference:** [Google Cloud Community Discussion](https://www.googlecloudcommunity.com/gc/Infrastructure-Compute-Storage/Cloud-Run-How-to-pass-arguments-with-values-that-contain-comma/m-p/784987)

---

## Working Patterns Quick Reference

| Use Case | Pattern | Example |
|----------|---------|---------|
| **Comma-separated values** | Custom delimiter `^CHAR^` | `--args="^|^--seasons=2021,2022|--limit=5"` |
| **Simple parameters** | Equals syntax (no quotes) | `--args=--start-date=2024-12-01,--end-date=2024-12-31` |
| **Boolean flags** | Single flag | `--args=--dry-run` |
| **Multiple flags** | Custom delimiter | `--args="^|^--dry-run|--verbose"` |
| **No arguments** | Omit `--args` | `gcloud run jobs execute job-name --region=us-west2` |

---

## Real-World Examples

### Multiple Seasons (Comma-Separated)

```bash
# Backfill multiple NBA seasons
gcloud run jobs execute nbac-gamebook-backfill \
    --region=us-west2 \
    --args="^|^--seasons=2021,2022,2023,2024"

# With additional parameters
gcloud run jobs execute nbac-gamebook-backfill \
    --region=us-west2 \
    --args="^|^--seasons=2021,2022,2023|--limit=100|--dry-run"
```

### Date Ranges (No Commas)

```bash
# Backfill specific date range
gcloud run jobs execute bdb-play-by-play-backfill \
    --region=us-west2 \
    --args=--start-date=2024-12-01,--end-date=2024-12-31

# Full season
gcloud run jobs execute bdb-play-by-play-backfill \
    --region=us-west2 \
    --args=--start-date=2024-10-01,--end-date=2025-06-30
```

### Single Values (Simple)

```bash
# Single season (no commas needed)
gcloud run jobs execute nba-injury-backfill \
    --region=us-west2 \
    --args=--seasons=2024

# Boolean flag only
gcloud run jobs execute processor-backfill \
    --region=us-west2 \
    --args=--dry-run
```

---

## Common Failures

**These patterns will ALL FAIL:**

```bash
# WRONG: Commas in values without delimiter syntax
--args="--seasons=2021,2022,2023"
# Error: unrecognized arguments: 2022 2023

# WRONG: Spaces in args
--args="--start-date 2024-12-01 --end-date 2024-12-31"
# Error: parsing errors

# WRONG: Shell-style quoting
--args="--start-date","2024-12-01","--end-date","2024-12-31"
# Error: cannot be specified multiple times

# WRONG: Mixing delimiters
--args=--start-date,2024-12-01,--end-date,2024-12-31
# Error: incorrect splitting
```

---

## Debugging Tips

### 1. Inspect Actual Arguments Passed

```bash
# Get the execution name
gcloud run jobs executions list \
    --job=your-job-name \
    --region=us-west2 \
    --limit=1

# Inspect what args were actually passed
gcloud run jobs executions describe EXECUTION-NAME \
    --region=us-west2 \
    --format="value(spec.template.spec.template.spec.containers[0].args)"
```

### 2. Test Locally First

```python
# Test your argparse with the exact args gcloud sends
import sys
import argparse

# Simulate what gcloud sends (WRONG parsing)
sys.argv = ["script.py", "--seasons=2021", "2022", "2023"]

parser = argparse.ArgumentParser()
parser.add_argument('--seasons')
args = parser.parse_args()  # Will fail: unrecognized arguments

# What you need (CORRECT parsing)
sys.argv = ["script.py", "--seasons=2021,2022,2023"]
args = parser.parse_args()  # Will work
print(args.seasons.split(','))  # ['2021', '2022', '2023']
```

### 3. Check Job Logs

```bash
# View logs from most recent execution
gcloud logging read \
    "resource.type=cloud_run_job AND resource.labels.job_name=your-job-name" \
    --limit=50 \
    --format=json
```

---

## Best Practices

### DO

- **Use custom delimiter for comma-separated values**
  ```bash
  --args="^|^--seasons=2021,2022,2023"
  ```

- **Use equals syntax for simple parameters (no quotes, no spaces)**
  ```bash
  --args=--start-date=2024-12-01,--end-date=2024-12-31
  ```

- **Test with simple cases first**
  ```bash
  # Test with single value before multiple
  --args=--seasons=2021
  # Then try multiple
  --args="^|^--seasons=2021,2022"
  ```

- **Verify args in execution description**
  ```bash
  gcloud run jobs executions describe EXECUTION-NAME --region=us-west2
  ```

### DON'T

- **Don't use spaces in args strings**
  ```bash
  # WRONG
  --args="--start-date 2024-12-01"
  ```

- **Don't forget delimiter syntax when values contain commas**
  ```bash
  # WRONG
  --args="--seasons=2021,2022,2023"
  # CORRECT
  --args="^|^--seasons=2021,2022,2023"
  ```

- **Don't assume shell escaping works**
  ```bash
  # WRONG - Shell escaping doesn't help
  --args="--seasons=\"2021,2022,2023\""
  ```

- **Don't mix syntaxes**
  ```bash
  # WRONG - Pick one approach
  --args="^|^--start-date=2024-01-01,--seasons=2021,2022"
  # CORRECT
  --args="^|^--start-date=2024-01-01|--seasons=2021,2022"
  ```

---

## Decision Matrix

**Which pattern should I use?**

| If your argument... | Use this pattern | Example |
|---------------------|------------------|---------|
| Contains commas | Custom delimiter `^CHAR^` | `--args="^|^--seasons=2021,2022"` |
| Is a date/simple value | Equals syntax | `--args=--start-date=2024-12-01` |
| Is a boolean flag | Single flag | `--args=--dry-run` |
| Has multiple simple params | Equals with commas | `--args=--start=2024-01-01,--end=2024-12-31` |
| Has mixed types | Custom delimiter for all | `--args="^|^--start=2024-01-01|--dry-run"` |

---

## Testing Checklist

Before running a full backfill job:

- [ ] Test with a single simple value first
- [ ] Verify args in execution description
- [ ] Check job logs for parsing errors
- [ ] Confirm script receives correct arguments
- [ ] Run with `--dry-run` flag if available
- [ ] Test with small date range before full range

---

## Common Error Messages and Solutions

| Error | Cause | Solution |
|-------|-------|----------|
| `unrecognized arguments: 2022 2023` | Commas split into separate args | Use custom delimiter: `--args="^|^--seasons=2021,2022,2023"` |
| `cannot be specified multiple times` | Shell parsing issue | Remove quotes around individual args |
| Unexpected splitting | Spaces in args string | Remove all spaces: `--args=--start=2024-01-01,--end=2024-12-31` |
| Arguments missing | Wrong delimiter character | Check delimiter matches throughout: `^|^....|....` |

---

## Alternative Approaches

**For complex configurations, consider:**

### Environment Variables
```bash
gcloud run jobs execute job-name \
    --region=us-west2 \
    --set-env-vars="SEASONS=2021,2022,2023,2024"
```

**Pros:** No parsing issues
**Cons:** Must modify code to read env vars

### Config Files
```bash
# Mount config via Cloud Storage volume
gcloud run jobs execute job-name \
    --region=us-west2 \
    --args="--config=/config/backfill.yaml"
```

**Pros:** Clean for complex configs
**Cons:** Requires file management

### Multiple Executions
```bash
# Run separate jobs for each season
for season in 2021 2022 2023; do
    gcloud run jobs execute job-name \
        --region=us-west2 \
        --args=--seasons=$season
done
```

**Pros:** Simple, no parsing issues
**Cons:** More executions, harder to monitor

---

## Quick Reference Card

**Copy-paste templates:**

```bash
# Comma-separated values (seasons, IDs, etc.)
--args="^|^--seasons=2021,2022,2023|--limit=100"

# Date ranges (no commas)
--args=--start-date=2024-01-01,--end-date=2024-12-31

# Boolean flags
--args=--dry-run

# Mixed parameters with commas
--args="^|^--seasons=2021,2022|--start-date=2024-01-01|--dry-run"

# Single value
--args=--limit=100
```

---

## Key Takeaway

**For comma-separated values, always use custom delimiter syntax:**

```bash
# This is the pattern that saves hours of debugging:
--args="^|^--param=value1,value2,value3|--other-param=value"
```

The `^|^` syntax tells gcloud to use `|` as the argument separator instead of `,`, preserving commas in your values.

---

## References

- **[Backfill Operations Guide](01-backfill-operations-guide.md)** - How to run backfills that use these patterns
- **[Cloud Run Jobs Documentation](https://cloud.google.com/run/docs/create-jobs)** - Official Google Cloud docs
- **[Args Parameter Reference](https://cloud.google.com/sdk/gcloud/reference/run/jobs/execute#--args)** - Official args syntax
- **[Community Discussion](https://www.googlecloudcommunity.com/gc/Infrastructure-Compute-Storage/Cloud-Run-How-to-pass-arguments-with-values-that-contain-comma/m-p/784987)** - Custom delimiter discovery

---

**Last Verified:** 2025-11-21
**Maintained By:** NBA Platform Team
