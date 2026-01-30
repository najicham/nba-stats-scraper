#!/usr/bin/env python3
"""
Team Offense Game Summary Processor - Composable Version

This demonstrates converting the existing TeamOffenseGameSummaryProcessor
to use the composable processor framework.

Key differences from the original:
1. Uses declarative configuration instead of imperative code
2. Components are reusable across processors
3. Easier to test individual components
4. Configuration is separated from logic

Original: team_offense_game_summary_processor.py (1400+ lines)
This version: ~200 lines of configuration + reusable components

Usage:
    python team_offense_composable.py --start-date 2025-01-01 --end-date 2025-01-01

Version: 1.0
Created: 2026-01-23
"""

import argparse
import logging
import sys
from typing import Dict, List

import pandas as pd

from shared.processors.components import (
    ComposableProcessor,
    ProcessorConfig,
    ProcessorConfigBuilder,
    BigQueryLoader,
    FallbackLoader,
    FallbackSource,
    FieldValidator,
    StatisticalValidator,
    StatCheck,
    FieldMapper,
    FieldMapping,
    ComputedFieldTransformer,
    ComputedField,
    HashTransformer,
    QualityTransformer,
    MetadataTransformer,
    ChainedTransformer,
    BigQueryMergeWriter,
    ComponentContext,
)

logger = logging.getLogger(__name__)


# =============================================================================
# COMPUTED FIELD FUNCTIONS
# Reusable calculations extracted from the original processor
# =============================================================================

def calculate_possessions(record: Dict) -> int:
    """
    Calculate estimated possessions.
    Formula: FGA + 0.44*FTA + TO - OREB
    """
    try:
        fga = record.get('fg_attempted', 0) or 0
        fta = record.get('ft_attempted', 0) or 0
        turnovers = record.get('turnovers', 0) or 0
        oreb = record.get('offensive_rebounds', 0) or 0

        possessions = fga + (0.44 * fta) + turnovers - oreb
        return int(round(possessions))
    except (TypeError, ValueError):
        return None


def calculate_offensive_rating(record: Dict) -> float:
    """
    Calculate offensive rating (points per 100 possessions).
    """
    try:
        points = record.get('points', 0) or 0
        possessions = record.get('possessions', 0) or 0

        if possessions <= 0:
            return None

        return round((points / possessions) * 100, 2)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def calculate_pace(record: Dict) -> float:
    """
    Calculate pace (possessions per 48 minutes).
    """
    try:
        possessions = record.get('possessions', 0) or 0
        game_minutes = 48  # Regulation

        if possessions <= 0:
            return None

        return round(possessions * (48 / game_minutes), 1)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def calculate_true_shooting_pct(record: Dict) -> float:
    """
    Calculate true shooting percentage.
    Formula: PTS / (2 * (FGA + 0.44*FTA))
    """
    try:
        points = record.get('points', 0) or 0
        fga = record.get('fg_attempted', 0) or 0
        fta = record.get('ft_attempted', 0) or 0

        total_shooting_possessions = 2 * (fga + 0.44 * fta)

        if total_shooting_possessions <= 0:
            return None

        ts_pct = points / total_shooting_possessions
        return round(ts_pct, 3)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def determine_win_flag(record: Dict) -> bool:
    """Determine if team won the game."""
    try:
        points = record.get('points', 0) or 0
        opponent_points = record.get('opponent_points', 0) or 0
        return points > opponent_points
    except (TypeError, ValueError):
        return False


def calculate_margin(record: Dict) -> int:
    """Calculate margin of victory/defeat."""
    try:
        points = record.get('points', 0) or 0
        opponent_points = record.get('opponent_points', 0) or 0
        return int(points - opponent_points)
    except (TypeError, ValueError):
        return None


def parse_overtime_periods(record: Dict) -> int:
    """Parse overtime periods from minutes string (240:00 = regulation)."""
    try:
        minutes_str = record.get('minutes', '')
        if not minutes_str:
            return 0

        total_minutes = int(minutes_str.split(':')[0])

        if total_minutes <= 240:
            return 0

        overtime_minutes = total_minutes - 240
        return overtime_minutes // 25
    except (TypeError, ValueError):
        return 0


# =============================================================================
# SQL QUERIES
# =============================================================================
# sql-template - These queries use BigQueryLoader which handles {placeholder} substitution

PRIMARY_QUERY = """
WITH team_boxscores_raw AS (
    SELECT
        game_id,
        nba_game_id,
        game_date,
        season_year,
        team_abbr,
        team_name,
        is_home,
        points,
        fg_made,
        fg_attempted,
        three_pt_made,
        three_pt_attempted,
        ft_made,
        ft_attempted,
        offensive_rebounds,
        defensive_rebounds,
        total_rebounds,
        assists,
        steals,
        blocks,
        turnovers,
        personal_fouls,
        minutes,
        processed_at,
        ROW_NUMBER() OVER (
            PARTITION BY game_id, team_abbr
            ORDER BY processed_at DESC
        ) as rn
    FROM `{project_id}.nba_raw.nbac_team_boxscore`
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
),

team_boxscores_dedup AS (
    SELECT * EXCEPT(rn) FROM team_boxscores_raw WHERE rn = 1
),

team_boxscores AS (
    SELECT
        tb.*,
        t2.team_abbr as opponent_team_abbr,
        t2.points as opponent_points
    FROM team_boxscores_dedup tb
    JOIN team_boxscores_dedup t2
        ON tb.game_id = t2.game_id
        AND tb.is_home != t2.is_home
)

SELECT * FROM team_boxscores
ORDER BY game_date DESC, game_id, team_abbr
"""

# sql-template - Uses BigQueryLoader which handles {placeholder} substitution
FALLBACK_QUERY = """
-- Reconstruct team stats from player boxscores when team boxscore unavailable
WITH player_stats AS (
    SELECT
        game_id, game_date, season_year, team_abbr,
        SUM(COALESCE(points, 0)) as points,
        SUM(COALESCE(field_goals_made, 0)) as fg_made,
        SUM(COALESCE(field_goals_attempted, 0)) as fg_attempted,
        SUM(COALESCE(three_pointers_made, 0)) as three_pt_made,
        SUM(COALESCE(three_pointers_attempted, 0)) as three_pt_attempted,
        SUM(COALESCE(free_throws_made, 0)) as ft_made,
        SUM(COALESCE(free_throws_attempted, 0)) as ft_attempted,
        SUM(COALESCE(total_rebounds, 0)) as total_rebounds,
        SUM(COALESCE(offensive_rebounds, 0)) as offensive_rebounds,
        SUM(COALESCE(defensive_rebounds, 0)) as defensive_rebounds,
        SUM(COALESCE(assists, 0)) as assists,
        SUM(COALESCE(turnovers, 0)) as turnovers,
        SUM(COALESCE(steals, 0)) as steals,
        SUM(COALESCE(blocks, 0)) as blocks,
        SUM(COALESCE(personal_fouls, 0)) as personal_fouls,
        MAX(processed_at) as processed_at,
        COUNT(*) as player_count
    FROM `{project_id}.nba_raw.nbac_gamebook_player_stats`
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
      AND player_status = 'active'
    GROUP BY game_id, game_date, season_year, team_abbr
    HAVING player_count >= 5
),

game_context AS (
    SELECT DISTINCT game_id,
        SPLIT(game_id, '_')[SAFE_OFFSET(2)] as home_team_abbr
    FROM player_stats
),

team_with_context AS (
    SELECT
        t.*,
        CASE WHEN t.team_abbr = g.home_team_abbr THEN TRUE ELSE FALSE END as is_home,
        t.game_id as nba_game_id,
        CAST(NULL AS STRING) as team_name,
        CAST(NULL AS STRING) as minutes
    FROM player_stats t
    LEFT JOIN game_context g ON t.game_id = g.game_id
),

with_opponent AS (
    SELECT
        t1.*,
        t2.team_abbr as opponent_team_abbr,
        t2.points as opponent_points
    FROM team_with_context t1
    JOIN team_with_context t2
        ON t1.game_id = t2.game_id AND t1.team_abbr != t2.team_abbr
)

SELECT * FROM with_opponent
ORDER BY game_date DESC, game_id, team_abbr
"""


# =============================================================================
# HASH FIELDS (for change detection)
# =============================================================================

HASH_FIELDS = [
    'game_id', 'nba_game_id', 'game_date', 'team_abbr',
    'opponent_team_abbr', 'season_year',
    'points_scored', 'fg_attempts', 'fg_makes', 'three_pt_attempts',
    'three_pt_makes', 'ft_attempts', 'ft_makes', 'rebounds',
    'assists', 'turnovers', 'personal_fouls',
    'offensive_rating', 'pace', 'possessions', 'ts_pct',
    'home_game', 'win_flag', 'margin_of_victory', 'overtime_periods',
]


# =============================================================================
# PROCESSOR IMPLEMENTATION
# =============================================================================

class TeamOffenseComposableProcessor(ComposableProcessor):
    """
    Team Offense Game Summary Processor using composable components.

    This is a rewrite of TeamOffenseGameSummaryProcessor using the new
    component framework. Compare with the original to see the difference.
    """

    @classmethod
    def get_config(cls) -> ProcessorConfig:
        """
        Build processor configuration using components.

        This replaces 500+ lines of imperative code with declarative config.
        """
        # Define primary and fallback loaders
        primary_loader = BigQueryLoader(
            query=PRIMARY_QUERY,
            source_name='nbac_team_boxscore',
            description='NBA.com team boxscore data',
        )

        fallback_loader = BigQueryLoader(
            query=FALLBACK_QUERY,
            source_name='reconstructed_from_players',
            description='Reconstructed from player boxscores',
        )

        loader = FallbackLoader(
            sources=[
                FallbackSource(
                    name='nbac_team_boxscore',
                    loader=lambda ctx: primary_loader.load(ctx),
                    quality_tier='gold',
                    quality_score=100.0,
                ),
                FallbackSource(
                    name='reconstructed_from_players',
                    loader=lambda ctx: fallback_loader.load(ctx),
                    quality_tier='silver',
                    quality_score=85.0,
                    is_reconstruction=True,
                ),
            ],
            on_all_fail='skip',
        )

        # Define validators
        field_validator = FieldValidator(
            required_fields=['game_id', 'team_abbr', 'points', 'fg_attempted'],
            optional_fields=['minutes', 'personal_fouls'],
        )

        stat_validator = StatisticalValidator(
            checks=[
                StatCheck(
                    name='fg_makes_lte_attempts',
                    check_type='lte',
                    field1='fg_made',
                    field2_or_min='fg_attempted',
                    description='FG makes should not exceed FG attempts',
                ),
                StatCheck(
                    name='points_range',
                    check_type='between',
                    field1='points',
                    field2_or_min=50,
                    max_val=200,
                    description='Team points should be between 50 and 200',
                    severity='warning',
                ),
            ]
        )

        # Define field mappings (rename source -> output)
        field_mapper = FieldMapper(
            mappings=[
                FieldMapping(source='game_id', target='game_id'),
                FieldMapping(source='nba_game_id', target='nba_game_id'),
                FieldMapping(source='game_date', target='game_date',
                            transform=lambda x: x.isoformat() if hasattr(x, 'isoformat') else str(x)),
                FieldMapping(source='team_abbr', target='team_abbr'),
                FieldMapping(source='opponent_team_abbr', target='opponent_team_abbr'),
                FieldMapping(source='season_year', target='season_year',
                            transform=lambda x: int(x) if x else None),
                FieldMapping(source='points', target='points_scored',
                            transform=lambda x: int(x) if x else None),
                FieldMapping(source='fg_attempted', target='fg_attempts',
                            transform=lambda x: int(x) if x else None),
                FieldMapping(source='fg_made', target='fg_makes',
                            transform=lambda x: int(x) if x else None),
                FieldMapping(source='three_pt_attempted', target='three_pt_attempts',
                            transform=lambda x: int(x) if x else None),
                FieldMapping(source='three_pt_made', target='three_pt_makes',
                            transform=lambda x: int(x) if x else None),
                FieldMapping(source='ft_attempted', target='ft_attempts',
                            transform=lambda x: int(x) if x else None),
                FieldMapping(source='ft_made', target='ft_makes',
                            transform=lambda x: int(x) if x else None),
                FieldMapping(source='total_rebounds', target='rebounds',
                            transform=lambda x: int(x) if x else None),
                FieldMapping(source='assists', target='assists',
                            transform=lambda x: int(x) if x else None),
                FieldMapping(source='turnovers', target='turnovers',
                            transform=lambda x: int(x) if x else None),
                FieldMapping(source='personal_fouls', target='personal_fouls',
                            transform=lambda x: int(x) if x else None),
                FieldMapping(source='is_home', target='home_game',
                            transform=lambda x: bool(x) if x is not None else False),
                # Pass through for computed fields
                FieldMapping(source='points', target='points'),
                FieldMapping(source='opponent_points', target='opponent_points'),
                FieldMapping(source='fg_attempted', target='fg_attempted'),
                FieldMapping(source='ft_attempted', target='ft_attempted'),
                FieldMapping(source='offensive_rebounds', target='offensive_rebounds'),
                FieldMapping(source='minutes', target='minutes'),
            ],
            include_unmapped=False,
        )

        # Define computed fields
        computed_transformer = ComputedFieldTransformer(
            fields=[
                ComputedField(
                    name='possessions',
                    compute=calculate_possessions,
                    depends_on=['fg_attempted', 'ft_attempted', 'turnovers', 'offensive_rebounds'],
                ),
                ComputedField(
                    name='offensive_rating',
                    compute=calculate_offensive_rating,
                    depends_on=['points', 'possessions'],
                ),
                ComputedField(
                    name='pace',
                    compute=calculate_pace,
                    depends_on=['possessions'],
                ),
                ComputedField(
                    name='ts_pct',
                    compute=calculate_true_shooting_pct,
                    depends_on=['points', 'fg_attempted', 'ft_attempted'],
                ),
                ComputedField(
                    name='win_flag',
                    compute=determine_win_flag,
                    depends_on=['points', 'opponent_points'],
                ),
                ComputedField(
                    name='margin_of_victory',
                    compute=calculate_margin,
                    depends_on=['points', 'opponent_points'],
                ),
                ComputedField(
                    name='overtime_periods',
                    compute=parse_overtime_periods,
                    depends_on=['minutes'],
                    default=0,
                ),
            ]
        )

        # Chain all transformers
        transformer = ChainedTransformer(
            transformers=[
                field_mapper,
                computed_transformer,
                HashTransformer(hash_fields=HASH_FIELDS),
                QualityTransformer(default_tier='gold', default_score=100.0),
                MetadataTransformer(include_source_tracking=True),
            ]
        )

        # Define writer
        writer = BigQueryMergeWriter(
            dataset_id='nba_analytics',
            table_name='team_offense_game_summary',
            primary_key_fields=['game_id', 'team_abbr'],
        )

        return ProcessorConfig(
            name='team_offense_game_summary',
            table_name='team_offense_game_summary',
            dataset_id='nba_analytics',
            loaders=[loader],
            validators=[field_validator, stat_validator],
            transformers=[transformer],
            writers=[writer],
            dependencies={
                'nba_raw.nbac_team_boxscore': {
                    'field_prefix': 'source_nbac_boxscore',
                    'description': 'Team box score statistics',
                    'date_field': 'game_date',
                    'check_type': 'date_range',
                    'expected_count_min': 20,
                    'max_age_hours_warn': 24,
                    'max_age_hours_fail': 72,
                    'critical': False,
                },
            },
            hash_fields=HASH_FIELDS,
            primary_key_fields=['game_id', 'team_abbr'],
            processing_strategy='MERGE_UPDATE',
        )


# =============================================================================
# CLI INTERFACE
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Team Offense Game Summary Processor (Composable)"
    )
    parser.add_argument('--start-date', required=True, help='YYYY-MM-DD')
    parser.add_argument('--end-date', required=True, help='YYYY-MM-DD')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Run processor
    try:
        processor = TeamOffenseComposableProcessor()
        success = processor.run({
            'start_date': args.start_date,
            'end_date': args.end_date,
        })

        print(f"\nProcessing stats: {processor.get_stats()}")
        sys.exit(0 if success else 1)

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
