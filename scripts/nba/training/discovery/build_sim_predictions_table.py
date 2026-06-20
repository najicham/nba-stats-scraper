#!/usr/bin/env python3
"""INC-4 step 1: load the walk-forward cache into a SCRATCH predictions table the
real BB pipeline can read (via query_predictions_with_supplements(predictions_table=...)).

Writes `nba_predictions.walkforward_sim_predictions` (schema-compatible with
player_prop_predictions for the columns the pipeline reads) under system_id
'wf_sim_v12noveg'. game_id is joined from player_game_summary. WRITE_TRUNCATE.
Does NOT touch production player_prop_predictions.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
import numpy as np
import pandas as pd
from google.cloud import bigquery

PROJECT_ID = "nba-props-platform"
SCRATCH = f"{PROJECT_ID}.nba_predictions.walkforward_sim_predictions"
SYSTEM_ID = "wf_sim_v12noveg"
FILES = ['results/nba_walkforward_2021/predictions_w56_r7.csv',
         'results/nba_walkforward_2022/predictions_w56_r7.csv',
         'results/nba_walkforward_clean/predictions_w56_r7.csv',
         'results/bb_simulator/predictions_2025_26_all_models.csv']

c = bigquery.Client(project=PROJECT_ID)
preds = pd.concat([pd.read_csv(f) for f in FILES if Path(f).exists()], ignore_index=True)
preds = preds.drop_duplicates(['game_date', 'player_lookup', 'line'])
preds['game_date'] = preds['game_date'].astype(str)
print(f"cache picks: {len(preds):,}")

# game_id per (player_lookup, game_date) from player_game_summary
gid = c.query(f"""
SELECT player_lookup, CAST(game_date AS STRING) game_date, ANY_VALUE(game_id) game_id
FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
WHERE game_date BETWEEN '2021-10-01' AND '2026-07-01'
  AND points IS NOT NULL AND minutes_played > 0
GROUP BY 1,2
""").to_dataframe()
print(f"game_id map: {len(gid):,}")

df = preds.merge(gid, on=['player_lookup', 'game_date'], how='inner')
print(f"after game_id join: {len(df):,} ({100*len(df)/len(preds):.1f}% kept)")

out = pd.DataFrame({
    'player_lookup': df['player_lookup'].astype(str),
    'game_id': df['game_id'].astype(str),
    'game_date': pd.to_datetime(df['game_date']).dt.date,
    'system_id': SYSTEM_ID,
    'predicted_points': df['predicted_points'].astype(float),
    'current_points_line': df['line'].astype(float),
    'recommendation': df['direction'].astype(str),
    'confidence_score': 0.8,
    'feature_quality_score': 1.0,
    'is_active': True,
    'is_actionable': True,
    'line_source': 'ODDS_API',
})
schema = [
    bigquery.SchemaField('player_lookup', 'STRING'),
    bigquery.SchemaField('game_id', 'STRING'),
    bigquery.SchemaField('game_date', 'DATE'),
    bigquery.SchemaField('system_id', 'STRING'),
    bigquery.SchemaField('predicted_points', 'FLOAT64'),
    bigquery.SchemaField('current_points_line', 'FLOAT64'),
    bigquery.SchemaField('recommendation', 'STRING'),
    bigquery.SchemaField('confidence_score', 'FLOAT64'),
    bigquery.SchemaField('feature_quality_score', 'FLOAT64'),
    bigquery.SchemaField('is_active', 'BOOL'),
    bigquery.SchemaField('is_actionable', 'BOOL'),
    bigquery.SchemaField('line_source', 'STRING'),
]
job = c.load_table_from_dataframe(out, SCRATCH, job_config=bigquery.LoadJobConfig(
    schema=schema, write_disposition='WRITE_TRUNCATE'))
job.result()
print(f"WROTE {SCRATCH}: {len(out):,} rows, system_id={SYSTEM_ID}")
print("by season-year:", out.assign(yr=out.game_date.astype(str).str[:4]).yr.value_counts().sort_index().to_dict())
