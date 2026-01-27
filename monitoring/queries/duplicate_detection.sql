-- P2 Alert: Duplicate Records Detected
-- Trigger: Any duplicates in player_game_summary
-- Action: Slack notification
--
-- Context: On 2026-01-26, 93 duplicate records were found in player_game_summary,
-- suggesting the processor ran multiple times or didn't properly deduplicate.
--
-- Usage:
--   bq query --use_legacy_sql=false --parameter=game_date:DATE:2026-01-26 < duplicate_detection.sql

WITH duplicate_check AS (
    SELECT
        game_date,
        game_id,
        player_lookup,
        COUNT(*) as record_count,
        STRING_AGG(DISTINCT source_file, ', ') as source_files,
        MIN(processed_at) as first_processed,
        MAX(processed_at) as last_processed
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date = @game_date
    GROUP BY game_date, game_id, player_lookup
    HAVING COUNT(*) > 1
),
duplicate_summary AS (
    SELECT
        @game_date as alert_date,
        COUNT(*) as duplicate_groups,
        SUM(record_count) as total_duplicate_records,
        SUM(record_count - 1) as excess_records,
        ARRAY_AGG(
            STRUCT(
                player_lookup,
                game_id,
                record_count,
                source_files,
                first_processed,
                last_processed,
                TIMESTAMP_DIFF(last_processed, first_processed, MINUTE) as minutes_between_runs
            )
            ORDER BY record_count DESC
            LIMIT 10
        ) as top_duplicates
    FROM duplicate_check
),
total_records AS (
    SELECT COUNT(*) as total
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date = @game_date
)
SELECT
    ds.alert_date,
    CURRENT_TIMESTAMP() as check_timestamp,
    COALESCE(ds.duplicate_groups, 0) as duplicate_groups,
    COALESCE(ds.total_duplicate_records, 0) as total_duplicate_records,
    COALESCE(ds.excess_records, 0) as excess_records,
    tr.total as total_records,

    -- Alert conditions
    CASE
        WHEN COALESCE(ds.duplicate_groups, 0) = 0 THEN 'OK'
        WHEN COALESCE(ds.duplicate_groups, 0) <= 5 THEN 'INFO'
        WHEN COALESCE(ds.duplicate_groups, 0) <= 20 THEN 'WARNING'
        ELSE 'CRITICAL'
    END as alert_level,

    CASE
        WHEN COALESCE(ds.duplicate_groups, 0) = 0 THEN
            'No duplicate records detected'
        WHEN COALESCE(ds.duplicate_groups, 0) <= 5 THEN
            CAST(ds.duplicate_groups AS STRING) || ' minor duplicates found (likely acceptable)'
        WHEN COALESCE(ds.duplicate_groups, 0) <= 20 THEN
            CAST(ds.duplicate_groups AS STRING) || ' duplicate groups detected. Check processor deduplication logic.'
        ELSE
            'CRITICAL: ' || CAST(ds.duplicate_groups AS STRING) || ' duplicate groups (' ||
            CAST(ds.excess_records AS STRING) || ' excess records). Processor may have run multiple times.'
    END as alert_message,

    -- Duplicate details
    CASE
        WHEN COALESCE(ds.duplicate_groups, 0) > 0 THEN ds.top_duplicates
        ELSE NULL
    END as duplicate_details,

    -- Root cause hints
    STRUCT(
        ROUND(COALESCE(ds.excess_records, 0) / tr.total * 100, 2) as duplicate_percentage,
        CASE
            WHEN COALESCE(ds.duplicate_groups, 0) > 50 THEN
                'Widespread duplicates suggest processor ran multiple times or merge issue'
            WHEN COALESCE(ds.duplicate_groups, 0) BETWEEN 5 AND 20 THEN
                'Moderate duplicates may indicate deduplication logic issue'
            ELSE NULL
        END as hint
    ) as diagnostics

FROM total_records tr
LEFT JOIN duplicate_summary ds ON TRUE
