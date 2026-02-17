-- Migration 001: Enrich model_registry with model family, feature set, and loss function metadata
--
-- Purpose: Single source of truth for model management. Enables DB-driven model loading,
-- multi-family retraining, and per-family performance monitoring.
--
-- Run once:
--   bq query --use_legacy_sql=false < bin/migrations/001_enrich_model_registry.sql
--
-- Created: 2026-02-16 (Session 273 - Model Management Overhaul)

-- Step 1: Add new columns
ALTER TABLE `nba-props-platform.nba_predictions.model_registry`
  ADD COLUMN IF NOT EXISTS model_family STRING,
  ADD COLUMN IF NOT EXISTS feature_set STRING,
  ADD COLUMN IF NOT EXISTS loss_function STRING,
  ADD COLUMN IF NOT EXISTS quantile_alpha FLOAT64,
  ADD COLUMN IF NOT EXISTS enabled BOOL,
  ADD COLUMN IF NOT EXISTS strengths_json STRING,
  ADD COLUMN IF NOT EXISTS evaluation_n_edge_3plus INT64;
-- NOTE: evaluation_hit_rate_edge_3plus already exists in the table

-- Step 2: Backfill existing models

-- V9 champion (production)
UPDATE `nba-props-platform.nba_predictions.model_registry`
SET model_family = 'v9_mae',
    feature_set = 'v9',
    loss_function = 'MAE',
    quantile_alpha = NULL,
    enabled = TRUE
WHERE model_id LIKE 'catboost_v9_33features%' AND is_production = TRUE;

-- V9 non-production MAE models
UPDATE `nba-props-platform.nba_predictions.model_registry`
SET model_family = 'v9_mae',
    feature_set = 'v9',
    loss_function = 'MAE',
    enabled = CASE WHEN status = 'active' THEN TRUE ELSE FALSE END
WHERE model_id LIKE 'catboost_v9%'
  AND model_id NOT LIKE '%q43%'
  AND model_id NOT LIKE '%q45%'
  AND model_id NOT LIKE 'catboost_v12%'
  AND model_family IS NULL;

-- Q43 shadow models
UPDATE `nba-props-platform.nba_predictions.model_registry`
SET model_family = 'v9_q43',
    feature_set = 'v9',
    loss_function = 'Quantile:alpha=0.43',
    quantile_alpha = 0.43,
    enabled = CASE WHEN status = 'active' THEN TRUE ELSE FALSE END
WHERE model_id LIKE '%q43%'
  AND model_family IS NULL;

-- Q45 shadow models
UPDATE `nba-props-platform.nba_predictions.model_registry`
SET model_family = 'v9_q45',
    feature_set = 'v9',
    loss_function = 'Quantile:alpha=0.45',
    quantile_alpha = 0.45,
    enabled = CASE WHEN status = 'active' THEN TRUE ELSE FALSE END
WHERE model_id LIKE '%q45%'
  AND model_family IS NULL;

-- V12 shadow models
UPDATE `nba-props-platform.nba_predictions.model_registry`
SET model_family = 'v12_noveg_mae',
    feature_set = 'v12_noveg',
    loss_function = 'MAE',
    quantile_alpha = NULL,
    enabled = CASE WHEN status = 'active' THEN TRUE ELSE FALSE END
WHERE model_id LIKE 'catboost_v12%'
  AND model_family IS NULL;
