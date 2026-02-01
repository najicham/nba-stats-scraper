# Sonnet Chat Handoff Prompts

**Created:** Session 69
**Purpose:** Copy-paste prompts for Sonnet execution chats

---

## Chat 1: Activate Scheduler + Run February Retrain

### Prompt

```
Read docs/08-projects/current/ml-monthly-retraining/EXECUTION-TASKS.md

Execute these two tasks in order:

**Task 1: Activate Cloud Scheduler**
- Review and run the deploy script at orchestration/cloud_functions/monthly_retrain/deploy.sh
- Verify the scheduler job was created
- If there are issues with the deploy script, fix them

**Task 2: Run February Retrain**
- First do a dry run to verify the command works
- Then execute the actual retrain
- Document the results (MAE, hit rates, sample sizes)

After completing, provide a summary in this format:

## Task 1: Activate Scheduler
- Status: ✅/❌
- Scheduler job name:
- Schedule:
- Any issues:

## Task 2: February Retrain
- Status: ✅/❌
- MAE:
- High-edge hit rate:
- High-edge bets:
- Model file saved:
- Recommendation (promote/wait/investigate):
```

---

## Chat 2: Enhance quick_retrain.py

### Prompt

```
Read docs/08-projects/current/ml-monthly-retraining/EXECUTION-TASKS.md

Execute Task 4: Enhance quick_retrain.py

Add these three enhancements to ml/experiments/quick_retrain.py:

1. **Recency Weighting** (--half-life argument)
   - Exponential decay weighting for sample weights
   - Pass to model.fit() when specified

2. **Hyperparameter Arguments** (--depth, --learning-rate, --l2-reg)
   - Allow customization of CatBoost parameters
   - Use sensible defaults matching current behavior

3. **Feature Set Selection** (--feature-set argument)
   - Support: all, no_vegas, core, stats_only
   - Define the feature lists as shown in EXECUTION-TASKS.md

After implementing, test each with --dry-run to verify arguments work.

Provide a summary of changes made and test results.
```

---

## Chat 3: Run Window Experiments

### Prompt

```
Read docs/08-projects/current/ml-monthly-retraining/EXECUTION-TASKS.md

Execute Task 5: Run Window Experiments

Run all 5 window size experiments (W1-W5) using the commands in the doc.

After all experiments complete, query the results:

bq query --use_legacy_sql=false "
SELECT
    experiment_name,
    JSON_VALUE(config_json, '$.train_days') as train_days,
    JSON_VALUE(results_json, '$.mae') as mae,
    JSON_VALUE(results_json, '$.hit_rate_high_edge') as hr_high_edge,
    JSON_VALUE(results_json, '$.bets_high_edge') as n_high_edge
FROM nba_predictions.ml_experiments
WHERE experiment_name LIKE 'EXP_W%'
ORDER BY experiment_name"

Provide analysis:
- Which window size performed best on high-edge hit rate?
- Which had best MAE?
- Are sample sizes sufficient for conclusions?
- Recommendation for default training window strategy
```

---

## Chat 4: Pre-Retrain Validation (Optional, P2)

### Prompt

```
Read docs/08-projects/current/ml-monthly-retraining/EXECUTION-TASKS.md

Execute Task 3: Add Pre-Retrain Validation

Create ml/experiments/pre_retrain_validation.py with these checks:

1. Feature store completeness (records, date coverage)
2. Vegas line coverage percentage
3. Data quality (no NULLs in critical features, reasonable ranges)

The script should:
- Accept --train-start and --train-end arguments
- Query BigQuery to validate data
- Print clear PASS/FAIL output
- Exit with code 0 (pass) or 1 (fail)

Test with:
python ml/experiments/pre_retrain_validation.py \
    --train-start 2025-11-02 --train-end 2026-01-31

Provide the validation output.
```

---

## Execution Order

```
Chat 1 (Tasks 1+2)
      │
      ├── If scheduler fails: debug and retry
      │
      └── If retrain succeeds:
            │
            ├── Chat 2 (Task 4) - Can run in parallel
            │
            └── Chat 3 (Task 5) - Run after Chat 1 complete
                                  (needs baseline to compare)
```

---

## Reporting Back

After each chat completes, report back here with:

1. **Status:** Success / Partial / Failed
2. **Key Results:** Metrics, files created
3. **Issues:** Anything that went wrong
4. **Questions:** Anything needing Opus-level decision

I'll help analyze results and adjust strategy as needed.

---

*Session 69 - Ready for execution*
