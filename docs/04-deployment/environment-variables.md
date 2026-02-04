# Environment Variables Reference

This document provides a comprehensive reference for all environment variables used to configure the NBA Stats Scraper system.

## Table of Contents

- [Parallelization Configuration](#parallelization-configuration)
- [Usage Examples](#usage-examples)
- [Cloud Run Deployment](#cloud-run-deployment)
- [Local Development](#local-development)

---

## Parallelization Configuration

The system supports runtime configuration of worker thread counts for parallel processing across multiple data processors. This allows tuning for different deployment environments (local development, Cloud Run, etc.) without code changes.

### Global Fallback

**`PARALLELIZATION_WORKERS`** (default: varies by processor)
- Global default worker count for all processors that don't have a specific override
- If not set, each processor uses its own code default
- Type: Integer
- Recommended range: 1-16 (depends on CPU count and memory)

### Processor-Specific Overrides

Each processor can be configured individually using its specific environment variable. These take precedence over the global `PARALLELIZATION_WORKERS` setting.

#### Analytics Processors

**`PGS_WORKERS`** - Player Game Summary
- Processor: `player_game_summary_processor.py`
- Code default: 10
- Description: Controls parallelization for player-game record processing
- Memory impact: Medium (processes individual game records)

**`UPGC_WORKERS`** - Upcoming Player Game Context
- Processor: `upcoming_player_game_context_processor.py`
- Code default: 10
- Description: Controls parallelization for upcoming game context generation
- Memory impact: High (loads multiple completeness datasets)

#### Precompute Processors

**`PCF_WORKERS`** - Player Composite Factors
- Processor: `player_composite_factors_processor.py`
- Code default: 10
- Description: Controls parallelization for composite factor calculations
- Memory impact: High (computes complex metrics)

**`MLFS_WORKERS`** - ML Feature Store
- Processor: `ml_feature_store_processor.py`
- Code default: 10
- Description: Controls parallelization for ML feature generation
- Memory impact: Very High (most memory-intensive processor)

**`PDC_WORKERS`** - Player Daily Cache
- Processor: `player_daily_cache_processor.py`
- Code default: 8
- Description: Controls parallelization for daily cache building
- Memory impact: Medium-High (caches recent data)

**`PSZA_WORKERS`** - Player Shot Zone Analysis
- Processor: `player_shot_zone_analysis_processor.py`
- Code default: 10
- Description: Controls parallelization for shot zone analysis
- Memory impact: Medium (zone-based aggregations)

**`TDZA_WORKERS`** - Team Defense Zone Analysis
- Processor: `team_defense_zone_analysis_processor.py`
- Code default: 4
- Description: Controls parallelization for team defense zone analysis
- Memory impact: Low-Medium (team-level aggregations, fewer entities)
- Note: Lower default due to fewer teams vs players

### Fallback Chain

For each processor, the worker count is determined using this precedence:

1. **Specific processor variable** (e.g., `PCF_WORKERS`)
2. **Global fallback** (`PARALLELIZATION_WORKERS`)
3. **Code default** (varies by processor: 4, 8, or 10)
4. **CPU cap** - Final worker count is capped at `os.cpu_count()`

Example:
```python
# If PCF_WORKERS=12, PARALLELIZATION_WORKERS=6, code default=10, CPU count=8
# Result: min(12, 8) = 8 workers
#   - PCF_WORKERS (12) takes precedence
#   - Capped at CPU count (8)

# If PARALLELIZATION_WORKERS=6, code default=10, CPU count=8
# Result: min(6, 8) = 6 workers
#   - PARALLELIZATION_WORKERS (6) takes precedence over code default
#   - Within CPU cap (8)

# If no env vars set, code default=10, CPU count=8
# Result: min(10, 8) = 8 workers
#   - Code default (10) used
#   - Capped at CPU count (8)
```

---

## Usage Examples

### Default Behavior (No Environment Variables)

```bash
# No environment variables set
# Each processor uses its code default, capped at CPU count
python scripts/run_processor.py --processor PCF --start-date 2024-01-01
# Uses 10 workers (code default), capped at CPU count
```

### Global Configuration

```bash
# Set global worker count for all processors
export PARALLELIZATION_WORKERS=4
python scripts/run_processor.py --processor PCF --start-date 2024-01-01
# PCF uses 4 workers (global default)

python scripts/run_processor.py --processor MLFS --start-date 2024-01-01
# MLFS uses 4 workers (global default)
```

### Processor-Specific Override

```bash
# Set global default and specific override
export PARALLELIZATION_WORKERS=4
export MLFS_WORKERS=2  # Override for memory-intensive processor

python scripts/run_processor.py --processor PCF --start-date 2024-01-01
# PCF uses 4 workers (global default)

python scripts/run_processor.py --processor MLFS --start-date 2024-01-01
# MLFS uses 2 workers (specific override)
```

### Mixed Configuration

```bash
# Configure multiple processors differently
export PARALLELIZATION_WORKERS=8  # Default for most processors
export MLFS_WORKERS=2             # Reduce for high-memory processor
export PDC_WORKERS=6              # Moderate for medium-memory processor
export TDZA_WORKERS=4             # Keep default for team processor

# All processors will use their respective configurations
```

### One-Off Command

```bash
# Set variable for single command execution
PARALLELIZATION_WORKERS=2 python scripts/run_processor.py --processor PCF --start-date 2024-01-01

# Or with specific override
PCF_WORKERS=12 python scripts/run_processor.py --processor PCF --start-date 2024-01-01
```

---

## Cloud Run Deployment

### Setting Environment Variables in Cloud Run

You can configure worker counts at deployment time using the `gcloud` CLI or Cloud Console.

**CRITICAL: Always use `--update-env-vars` instead of `--set-env-vars`**

- `--update-env-vars` = **SAFE** - Merges with existing variables
- `--set-env-vars` = **DANGEROUS** - Replaces ALL variables (can wipe out critical vars like GCP_PROJECT_ID)

See Session 106/107 incident where `--set-env-vars` caused production outage by wiping environment variables.

#### Option 1: Command Line (gcloud)

```bash
# Update environment variables (SAFE - preserves existing vars)
gcloud run deploy nba-stats-scraper \
  --image gcr.io/YOUR_PROJECT/nba-stats-scraper:latest \
  --region us-central1 \
  --update-env-vars="PARALLELIZATION_WORKERS=4,MLFS_WORKERS=2,PDC_WORKERS=3"
```

#### Option 2: YAML Configuration

Create `cloud-run-config.yaml`:

```yaml
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: nba-stats-scraper
spec:
  template:
    spec:
      containers:
      - image: gcr.io/YOUR_PROJECT/nba-stats-scraper:latest
        env:
        - name: PARALLELIZATION_WORKERS
          value: "4"
        - name: MLFS_WORKERS
          value: "2"
        - name: PDC_WORKERS
          value: "3"
        - name: PCF_WORKERS
          value: "4"
        - name: PGS_WORKERS
          value: "6"
        - name: PSZA_WORKERS
          value: "4"
        - name: TDZA_WORKERS
          value: "2"
        - name: UPGC_WORKERS
          value: "4"
```

Deploy:
```bash
gcloud run services replace cloud-run-config.yaml --region us-central1
```

#### Option 3: Cloud Console

1. Navigate to Cloud Run service
2. Click "Edit & Deploy New Revision"
3. Expand "Variables & Secrets"
4. Add environment variables:
   - `PARALLELIZATION_WORKERS` = `4`
   - `MLFS_WORKERS` = `2`
   - etc.
5. Deploy revision

### Recommended Cloud Run Settings

Based on memory constraints and CPU allocation:

#### Low Memory (2GB - 4GB)
```bash
export PARALLELIZATION_WORKERS=2
export MLFS_WORKERS=1  # Most memory-intensive
export PDC_WORKERS=2
```

#### Medium Memory (4GB - 8GB)
```bash
export PARALLELIZATION_WORKERS=4
export MLFS_WORKERS=2
export PDC_WORKERS=3
```

#### High Memory (8GB+)
```bash
export PARALLELIZATION_WORKERS=6
export MLFS_WORKERS=4
export PDC_WORKERS=5
```

### Monitoring and Tuning

After deployment, monitor:
- **Memory usage**: Cloud Run metrics → Memory utilization
- **CPU usage**: Cloud Run metrics → CPU utilization
- **Execution time**: Cloud Run logs → Processing duration
- **Error rates**: Look for OOM (Out Of Memory) errors

Tuning guidelines:
- If seeing OOM errors: **Reduce** worker counts
- If CPU usage low (<50%): **Increase** worker counts
- If memory usage high (>80%): **Reduce** MLFS_WORKERS and PDC_WORKERS first
- Monitor log messages showing actual worker count used

---

## Local Development

### Setting Up for Local Testing

#### Option 1: Export in Shell

```bash
# Add to ~/.bashrc or ~/.zshrc for persistence
export PARALLELIZATION_WORKERS=8
export MLFS_WORKERS=4

# Or set for current session only
export PARALLELIZATION_WORKERS=8
```

#### Option 2: .env File (if using python-dotenv)

Create `.env` in project root:

```bash
# Global default
PARALLELIZATION_WORKERS=8

# Processor-specific overrides
MLFS_WORKERS=4
PDC_WORKERS=6
PCF_WORKERS=8
PGS_WORKERS=8
PSZA_WORKERS=6
TDZA_WORKERS=4
UPGC_WORKERS=8
```

#### Option 3: IDE Configuration

**VS Code** - `.vscode/launch.json`:
```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Run Processor",
      "type": "python",
      "request": "launch",
      "program": "${workspaceFolder}/scripts/run_processor.py",
      "env": {
        "PARALLELIZATION_WORKERS": "8",
        "MLFS_WORKERS": "4"
      },
      "args": ["--processor", "PCF", "--start-date", "2024-01-01"]
    }
  ]
}
```

**PyCharm** - Run Configuration:
1. Run → Edit Configurations
2. Select/create configuration
3. Environment variables: `PARALLELIZATION_WORKERS=8;MLFS_WORKERS=4`

### Testing Environment Variables

```bash
# Test that environment variables are respected
echo "Testing default behavior..."
python scripts/run_processor.py --processor PCF --start-date 2024-12-01 --end-date 2024-12-01

echo "Testing global override..."
PARALLELIZATION_WORKERS=2 python scripts/run_processor.py --processor PCF --start-date 2024-12-01 --end-date 2024-12-01

echo "Testing specific override..."
PCF_WORKERS=12 python scripts/run_processor.py --processor PCF --start-date 2024-12-01 --end-date 2024-12-01

# Check logs for: "Processing N players with X workers (parallel mode)"
# Verify X matches your configuration
```

### Recommended Local Settings

For typical development machines:

#### Laptop (4-8 cores, 8-16GB RAM)
```bash
export PARALLELIZATION_WORKERS=4
export MLFS_WORKERS=2
```

#### Desktop (8-16 cores, 16-32GB RAM)
```bash
export PARALLELIZATION_WORKERS=8
export MLFS_WORKERS=4
```

#### Workstation (16+ cores, 32GB+ RAM)
```bash
export PARALLELIZATION_WORKERS=12
export MLFS_WORKERS=6
```

---

## Best Practices

1. **Start Conservative**: Begin with lower worker counts and increase if resources allow
2. **Monitor Memory**: Watch for OOM errors, especially with MLFS and PDC processors
3. **CPU vs Memory**: More workers = more CPU utilization but also more memory usage
4. **Environment-Specific**: Use different settings for dev, staging, and production
5. **Document Changes**: Note worker count configurations in deployment documentation
6. **Test Incrementally**: When changing worker counts, test with small date ranges first
7. **Log Review**: Always check logs to confirm the actual worker count being used

---

## Troubleshooting

### Problem: Out of Memory Errors

**Symptoms**: Process crashes with OOM error, Cloud Run instance restarts

**Solution**:
```bash
# Reduce global workers
export PARALLELIZATION_WORKERS=2

# Or reduce specific high-memory processors
export MLFS_WORKERS=1
export PDC_WORKERS=2
```

### Problem: Slow Processing / Low CPU Utilization

**Symptoms**: CPU usage <50%, processing takes longer than expected

**Solution**:
```bash
# Increase workers (up to CPU count)
export PARALLELIZATION_WORKERS=8

# Check CPU count
python -c "import os; print(f'CPU count: {os.cpu_count()}')"
```

### Problem: Workers Not Respecting Environment Variables

**Symptoms**: Logs show unexpected worker count

**Troubleshooting**:
```bash
# Verify environment variable is set
echo $PARALLELIZATION_WORKERS
echo $PCF_WORKERS

# Check actual value in Python
python -c "import os; print(os.environ.get('PARALLELIZATION_WORKERS', 'NOT SET'))"

# Run with explicit setting
PCF_WORKERS=4 python scripts/run_processor.py --processor PCF --start-date 2024-12-01
```

### Problem: Environment Variables Not Persisting

**Solution**:
```bash
# Add to shell profile for persistence
echo 'export PARALLELIZATION_WORKERS=8' >> ~/.bashrc
source ~/.bashrc

# Or use .env file with python-dotenv library
```

---

## Version History

- **2025-12-05**: Initial version - Added parallelization worker configuration for 7 processors
