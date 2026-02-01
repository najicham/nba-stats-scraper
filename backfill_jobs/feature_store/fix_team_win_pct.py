#!/usr/bin/env python3
"""
Fix team_win_pct (feature index 24) in ml_feature_store_v2 for historical data.

Problem:
- team_win_pct was stuck at 0.5 for 2024-25 season (100% of ~25K records)
- Root cause: team_season_games data wasn't being passed to feature calculator
- Fixed in Nov 2025 for new data, but historical data still needs correction

Solution:
- Compute correct team_win_pct from bdl_player_boxscores (has home/away team scores)
- Update ml_feature_store_v2.features[24] with corrected values

Usage:
    # Dry run to see what would be fixed
    PYTHONPATH=. python backfill_jobs/feature_store/fix_team_win_pct.py \
        --start-date 2024-10-22 --end-date 2025-06-22 --dry-run

    # Execute the fix
    PYTHONPATH=. python backfill_jobs/feature_store/fix_team_win_pct.py \
        --start-date 2024-10-22 --end-date 2025-06-22

Created: Session 68, 2026-02-01
"""

import argparse
import logging
from datetime import date, timedelta
from typing import Dict, List, Optional
from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = "nba-props-platform"
TEAM_WIN_PCT_INDEX = 24  # 0-indexed position in features array


class TeamWinPctFixer:
    """Fix team_win_pct in ml_feature_store_v2 for historical data."""

    def __init__(self):
        self.client = bigquery.Client(project=PROJECT_ID)

    def compute_correct_team_win_pct(self, start_date: date, end_date: date) -> Dict:
        """
        Compute correct team_win_pct from bdl_player_boxscores.

        Uses cumulative wins/games BEFORE each game date (not including current game).

        Returns:
            Dict mapping (team_abbr, game_date) -> corrected win_pct
        """
        query = f"""
        WITH game_results AS (
            -- Get unique games with winner
            SELECT DISTINCT
                game_id,
                game_date,
                home_team_abbr,
                away_team_abbr,
                home_team_score,
                away_team_score,
                CASE
                    WHEN home_team_score > away_team_score THEN home_team_abbr
                    WHEN away_team_score > home_team_score THEN away_team_abbr
                    ELSE NULL  -- Tie (shouldn't happen in NBA)
                END as winner
            FROM `{PROJECT_ID}.nba_raw.bdl_player_boxscores`
            WHERE game_date >= DATE('{start_date}') - 90  -- Include games before start for warmup
                AND game_date <= DATE('{end_date}')
                AND home_team_score > 0 AND away_team_score > 0  -- Final games only
        ),
        team_games AS (
            -- Unpivot to team-level games
            SELECT home_team_abbr as team, game_date, winner = home_team_abbr as won FROM game_results
            UNION ALL
            SELECT away_team_abbr as team, game_date, winner = away_team_abbr as won FROM game_results
        ),
        team_cumulative AS (
            -- Compute cumulative wins BEFORE each game
            SELECT
                team,
                game_date,
                SUM(CASE WHEN won THEN 1 ELSE 0 END) OVER (
                    PARTITION BY team
                    ORDER BY game_date
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                ) as wins_before,
                COUNT(*) OVER (
                    PARTITION BY team
                    ORDER BY game_date
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                ) as games_before
            FROM team_games
        )
        SELECT
            team,
            game_date,
            wins_before,
            games_before,
            CASE
                WHEN games_before >= 5 THEN ROUND(SAFE_DIVIDE(wins_before, games_before), 9)
                ELSE 0.5  -- Default for early season
            END as correct_win_pct
        FROM team_cumulative
        WHERE game_date >= DATE('{start_date}') AND game_date <= DATE('{end_date}')
        ORDER BY team, game_date
        """

        logger.info("Computing correct team_win_pct from bdl_player_boxscores...")
        result = self.client.query(query).result()

        # Build lookup dict
        win_pct_lookup = {}
        for row in result:
            key = (row.team, row.game_date)
            win_pct_lookup[key] = row.correct_win_pct

        logger.info(f"Computed win_pct for {len(win_pct_lookup):,} team-date combinations")
        return win_pct_lookup

    def get_records_needing_fix(self, start_date: date, end_date: date) -> List[Dict]:
        """
        Get feature store records where team_win_pct = 0.5 (constant/broken).

        Returns list of records with player_lookup, game_date, team_abbr, current features.
        """
        query = f"""
        SELECT
            fs.player_lookup,
            fs.game_date,
            pgs.team_abbr,
            fs.features,
            fs.feature_names,
            CAST(fs.features[OFFSET({TEAM_WIN_PCT_INDEX})] AS FLOAT64) as current_win_pct
        FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` fs
        JOIN `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
            ON fs.player_lookup = pgs.player_lookup AND fs.game_date = pgs.game_date
        WHERE fs.game_date >= DATE('{start_date}')
            AND fs.game_date <= DATE('{end_date}')
            AND ARRAY_LENGTH(fs.features) >= 33
            AND CAST(fs.features[OFFSET({TEAM_WIN_PCT_INDEX})] AS FLOAT64) = 0.5
        ORDER BY fs.game_date, fs.player_lookup
        """

        logger.info(f"Finding records needing fix from {start_date} to {end_date}...")
        result = self.client.query(query).result()

        records = []
        for row in result:
            records.append({
                'player_lookup': row.player_lookup,
                'game_date': row.game_date,
                'team_abbr': row.team_abbr,
                'features': list(row.features),
                'current_win_pct': row.current_win_pct
            })

        logger.info(f"Found {len(records):,} records with team_win_pct = 0.5")
        return records

    def apply_fixes(self, records: List[Dict], win_pct_lookup: Dict, dry_run: bool = True) -> Dict:
        """
        Apply corrected team_win_pct to feature store records.

        Args:
            records: Records needing fix
            win_pct_lookup: Dict mapping (team, date) -> correct win_pct
            dry_run: If True, only show what would be done

        Returns:
            Summary statistics
        """
        stats = {
            'total_records': len(records),
            'fixed': 0,
            'skipped_no_team': 0,
            'skipped_no_lookup': 0,
            'new_values': []
        }

        updates = []

        for record in records:
            team = record['team_abbr']
            game_date = record['game_date']

            if not team:
                stats['skipped_no_team'] += 1
                continue

            key = (team, game_date)
            if key not in win_pct_lookup:
                stats['skipped_no_lookup'] += 1
                continue

            correct_win_pct = win_pct_lookup[key]
            old_win_pct = record['current_win_pct']

            if correct_win_pct != old_win_pct:
                # Update features array
                new_features = record['features'].copy()
                new_features[TEAM_WIN_PCT_INDEX] = correct_win_pct

                updates.append({
                    'player_lookup': record['player_lookup'],
                    'game_date': record['game_date'],
                    'new_features': new_features,
                    'old_win_pct': old_win_pct,
                    'new_win_pct': correct_win_pct
                })

                stats['fixed'] += 1
                stats['new_values'].append(correct_win_pct)

        # Show sample of fixes
        logger.info(f"\n{'='*60}")
        logger.info("SAMPLE FIXES (first 10)")
        logger.info(f"{'='*60}")
        for update in updates[:10]:
            logger.info(f"  {update['player_lookup']} on {update['game_date']}: "
                       f"0.5 -> {update['new_win_pct']:.3f}")

        # Show distribution of new values
        if stats['new_values']:
            from collections import Counter
            bins = Counter(round(v, 1) for v in stats['new_values'])
            logger.info(f"\nNEW VALUE DISTRIBUTION:")
            for val in sorted(bins.keys()):
                logger.info(f"  {val:.1f}: {bins[val]:,} records")

        if dry_run:
            logger.info(f"\n[DRY RUN] Would update {stats['fixed']:,} records")
            return stats

        # Execute updates in batches
        if updates:
            logger.info(f"\nApplying {len(updates):,} updates in batches...")
            self._batch_update_features(updates)

        return stats

    def _batch_update_features(self, updates: List[Dict], batch_size: int = 1000):
        """
        Update feature store records in batches using MERGE statement.

        BigQuery doesn't support direct array element updates, so we need to
        update the entire features array.
        """
        # Create temp table with updates
        temp_table_id = f"{PROJECT_ID}.nba_predictions._temp_win_pct_fixes"

        # Prepare rows for temp table
        rows = []
        for update in updates:
            rows.append({
                'player_lookup': update['player_lookup'],
                'game_date': str(update['game_date']),
                'features': update['new_features']
            })

        # Create/load temp table
        logger.info(f"Loading {len(rows):,} updates to temp table...")

        job_config = bigquery.LoadJobConfig(
            schema=[
                bigquery.SchemaField("player_lookup", "STRING"),
                bigquery.SchemaField("game_date", "DATE"),
                bigquery.SchemaField("features", "FLOAT64", mode="REPEATED"),
            ],
            write_disposition="WRITE_TRUNCATE",
        )

        # Load in batches
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i+batch_size]
            load_job = self.client.load_table_from_json(
                batch, temp_table_id, job_config=job_config
            )
            load_job.result()
            logger.info(f"  Loaded batch {i//batch_size + 1} ({len(batch):,} rows)")

        # Execute MERGE
        merge_query = f"""
        MERGE `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` T
        USING `{temp_table_id}` S
        ON T.player_lookup = S.player_lookup AND T.game_date = S.game_date
        WHEN MATCHED THEN
            UPDATE SET features = S.features, updated_at = CURRENT_TIMESTAMP()
        """

        logger.info("Executing MERGE...")
        merge_job = self.client.query(merge_query)
        result = merge_job.result()
        logger.info(f"MERGE complete. Modified {merge_job.num_dml_affected_rows:,} rows")

        # Cleanup temp table
        self.client.delete_table(temp_table_id, not_found_ok=True)
        logger.info("Cleaned up temp table")


def main():
    parser = argparse.ArgumentParser(description='Fix team_win_pct in ml_feature_store_v2')
    parser.add_argument('--start-date', type=str, required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without executing')
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start_date)
    end_date = date.fromisoformat(args.end_date)

    logger.info("="*60)
    logger.info("TEAM_WIN_PCT FIX FOR ML_FEATURE_STORE_V2")
    logger.info("="*60)
    logger.info(f"Date range: {start_date} to {end_date}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info("")

    fixer = TeamWinPctFixer()

    # Step 1: Compute correct win percentages
    win_pct_lookup = fixer.compute_correct_team_win_pct(start_date, end_date)

    # Step 2: Find records needing fix
    records = fixer.get_records_needing_fix(start_date, end_date)

    if not records:
        logger.info("No records need fixing!")
        return

    # Step 3: Apply fixes
    stats = fixer.apply_fixes(records, win_pct_lookup, dry_run=args.dry_run)

    # Summary
    logger.info("")
    logger.info("="*60)
    logger.info("SUMMARY")
    logger.info("="*60)
    logger.info(f"Total records with team_win_pct = 0.5: {stats['total_records']:,}")
    logger.info(f"Records fixed: {stats['fixed']:,}")
    logger.info(f"Skipped (no team): {stats['skipped_no_team']:,}")
    logger.info(f"Skipped (no lookup): {stats['skipped_no_lookup']:,}")

    if args.dry_run:
        logger.info("")
        logger.info("To execute the fix, run without --dry-run")


if __name__ == '__main__':
    main()
