"""
JSON Output Formatter

Formats validation results as JSON for automation and downstream processing.
"""

import json
from datetime import date, datetime
from typing import Optional, List, Any, Dict
from dataclasses import asdict

from shared.validation.validators.base import ValidationStatus


def format_validation_json(report, pretty: bool = True) -> str:
    """
    Format validation report as JSON.

    Args:
        report: ValidationReport to format
        pretty: Whether to pretty-print with indentation

    Returns:
        JSON string
    """
    # Build the JSON structure
    output = {
        'validation_date': report.game_date.isoformat(),
        'validation_timestamp': datetime.utcnow().isoformat() + 'Z',
        'overall_status': report.overall_status,
    }

    # Context
    matchups = [
        f"{g.away_team} @ {g.home_team}"
        for g in report.schedule_context.games
    ]
    output['context'] = {
        'season_string': report.schedule_context.season_string,
        'season_year': report.schedule_context.season_year,
        'season_day': report.schedule_context.season_day,
        'is_bootstrap': report.schedule_context.is_bootstrap,
        'game_count': report.schedule_context.game_count,
        'teams_playing': sorted(list(report.schedule_context.teams_playing)),
        'matchups': matchups,
        'is_valid_processing_date': report.schedule_context.is_valid_processing_date,
        'skip_reason': report.schedule_context.skip_reason,
    }

    # Time context (if available)
    if report.time_context:
        output['time_context'] = {
            'is_today': report.time_context.is_today,
            'is_yesterday': report.time_context.is_yesterday,
            'is_historical': report.time_context.is_historical,
            'current_time_et': report.time_context.current_time_et.isoformat(),
        }

    # Player universe
    output['player_universe'] = {
        'total_rostered': report.player_universe.total_rostered,
        'active': report.player_universe.total_active,
        'dnp': report.player_universe.total_dnp,
        'inactive': report.player_universe.total_inactive,
        'with_props': report.player_universe.total_with_props,
        'teams': sorted(list(report.player_universe.teams)),
    }

    # Phase results
    output['phases'] = {}
    for phase_result in report.phase_results:
        phase_data = {
            'status': phase_result.status.value,
            'total_records': phase_result.total_records,
            'issues': phase_result.issues,
            'warnings': phase_result.warnings,
            'tables': {},
        }

        for table_name, table in phase_result.tables.items():
            table_data = {
                'status': table.status.value,
                'record_count': table.record_count,
                'expected_count': table.expected_count,
                'completeness_pct': table.completeness_pct,
            }

            if table.player_count is not None:
                table_data['player_count'] = table.player_count
                table_data['expected_players'] = table.expected_players

            if table.quality:
                table_data['quality'] = {
                    'gold': table.quality.gold,
                    'silver': table.quality.silver,
                    'bronze': table.quality.bronze,
                    'poor': table.quality.poor,
                    'unusable': table.quality.unusable,
                }

            if table.issues:
                table_data['issues'] = table.issues
            if table.warnings:
                table_data['warnings'] = table.warnings

            phase_data['tables'][table_name] = table_data

        output['phases'][str(phase_result.phase)] = phase_data

    # Run history summary (if available)
    if report.run_history:
        output['run_history'] = {
            'total_runs': report.run_history.total_runs,
            'successful': report.run_history.successful_runs,
            'failed': report.run_history.failed_runs,
            'partial': report.run_history.partial_runs,
            'total_duration_seconds': report.run_history.total_duration_seconds,
            'errors_count': len(report.run_history.errors),
            'dependency_failures_count': len(report.run_history.dependency_failures),
            'alerts_sent_count': len(report.run_history.alerts_sent),
        }

    # Orchestration state (if available)
    if report.orchestration_state and report.orchestration_state.firestore_available:
        output['orchestration'] = {}
        for phase_num, phase_state in report.orchestration_state.phases.items():
            output['orchestration'][str(phase_num)] = {
                'completed_count': phase_state.completed_count,
                'expected_count': phase_state.expected_count,
                'is_complete': phase_state.is_complete,
                'triggered': phase_state.triggered,
            }

    # Issues and warnings
    output['issues'] = report.issues
    output['warnings'] = report.warnings

    # Missing players (if available)
    if report.missing_players:
        output['missing_players'] = report.missing_players

    # Quality summary across all phases
    quality_summary = {'gold': 0, 'silver': 0, 'bronze': 0, 'poor': 0, 'unusable': 0}
    for phase_result in report.phase_results:
        for table in phase_result.tables.values():
            if table.quality:
                quality_summary['gold'] += table.quality.gold
                quality_summary['silver'] += table.quality.silver
                quality_summary['bronze'] += table.quality.bronze
                quality_summary['poor'] += table.quality.poor
                quality_summary['unusable'] += table.quality.unusable
    output['quality_summary'] = quality_summary

    # Format output
    if pretty:
        return json.dumps(output, indent=2, default=str)
    else:
        return json.dumps(output, default=str)


def print_validation_json(report, pretty: bool = True):
    """Print validation report as JSON to stdout."""
    print(format_validation_json(report, pretty))
