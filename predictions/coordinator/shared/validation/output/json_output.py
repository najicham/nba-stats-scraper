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
        'dnp': report.player_universe.total_dnp if report.player_universe.has_dnp_tracking else None,
        'inactive': report.player_universe.total_inactive if report.player_universe.has_dnp_tracking else None,
        'with_props': report.player_universe.total_with_props,
        'teams': sorted(list(report.player_universe.teams)),
        'source': report.player_universe.source,
        'has_dnp_tracking': report.player_universe.has_dnp_tracking,
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


def format_chain_validation_json(
    chain_validations: Dict[str, Any],
    maintenance: Any = None,
    pretty: bool = True,
) -> str:
    """
    Format chain validations as JSON.

    Args:
        chain_validations: Dict mapping chain_name -> ChainValidation
        maintenance: Optional MaintenanceValidation
        pretty: Whether to pretty-print

    Returns:
        JSON string
    """
    output = {
        'chains': {},
        'summary': {
            'total': len(chain_validations),
            'complete': 0,
            'partial': 0,
            'missing': 0,
        }
    }

    for chain_name, cv in chain_validations.items():
        chain_data = {
            'status': cv.status,
            'severity': cv.chain.severity,
            'description': cv.chain.description,
            'primary_available': cv.primary_available,
            'fallback_used': cv.fallback_used,
            'impact_message': cv.impact_message,
            'sources': [],
        }

        for sv in cv.sources:
            source_data = {
                'name': sv.source.name,
                'is_primary': sv.source.is_primary,
                'is_virtual': sv.source.is_virtual,
                'quality_tier': sv.source.quality_tier,
                'quality_score': sv.source.quality_score,
                'gcs_file_count': sv.gcs_file_count,
                'bq_record_count': sv.bq_record_count,
                'status': sv.status,
            }
            chain_data['sources'].append(source_data)

        output['chains'][chain_name] = chain_data

        # Update summary
        if cv.status == 'complete':
            output['summary']['complete'] += 1
        elif cv.status == 'partial':
            output['summary']['partial'] += 1
        else:
            output['summary']['missing'] += 1

    # Add maintenance if provided
    if maintenance:
        output['maintenance'] = {
            'is_current': maintenance.is_current,
            'unresolved_players': maintenance.unresolved_players,
        }
        if maintenance.roster_chain:
            output['maintenance']['roster_chain'] = {
                'status': maintenance.roster_chain.status,
                'sources': [
                    {
                        'name': sv.source.name,
                        'bq_record_count': sv.bq_record_count,
                        'status': sv.status,
                    }
                    for sv in maintenance.roster_chain.sources
                ]
            }
        if maintenance.registry_status:
            output['maintenance']['registry'] = {
                'total_players': maintenance.registry_status.total_players,
                'is_current': maintenance.registry_status.is_current,
                'staleness_days': maintenance.registry_status.staleness_days,
            }

    if pretty:
        return json.dumps(output, indent=2, default=str)
    else:
        return json.dumps(output, default=str)


def format_date_range_json(
    chain_results: List[Any],
    start_date: date,
    end_date: date,
    pretty: bool = True,
) -> str:
    """
    Format date range validation results as JSON with comprehensive summary.

    Args:
        chain_results: List of ChainRangeResult objects
        start_date: First date in range
        end_date: Last date in range
        pretty: Whether to pretty-print

    Returns:
        JSON string with range summary and per-date details
    """
    # Calculate summary statistics
    total_dates = len(chain_results)
    dates_complete = sum(1 for r in chain_results if r.chains_complete == r.total_chains)
    dates_partial = sum(1 for r in chain_results if 0 < r.chains_complete < r.total_chains)
    dates_missing = sum(1 for r in chain_results if r.chains_complete == 0)

    # Calculate chain statistics across all dates
    total_chain_checks = sum(r.total_chains for r in chain_results)
    total_chains_complete = sum(r.chains_complete for r in chain_results)
    total_chains_partial = sum(r.chains_partial for r in chain_results)
    total_chains_missing = sum(r.chains_missing for r in chain_results)

    # Calculate phase statistics if available
    phase_stats = {3: {'complete': 0, 'partial': 0, 'missing': 0, 'bootstrap': 0},
                   4: {'complete': 0, 'partial': 0, 'missing': 0, 'bootstrap': 0},
                   5: {'complete': 0, 'partial': 0, 'missing': 0, 'bootstrap': 0}}

    for r in chain_results:
        if hasattr(r, 'phase_statuses'):
            for phase, status in r.phase_statuses.items():
                if status == 'complete':
                    phase_stats[phase]['complete'] += 1
                elif status == 'partial':
                    phase_stats[phase]['partial'] += 1
                elif status == 'bootstrap_skip':
                    phase_stats[phase]['bootstrap'] += 1
                else:
                    phase_stats[phase]['missing'] += 1

    # Build output
    output = {
        'validation_timestamp': datetime.utcnow().isoformat() + 'Z',
        'range': {
            'start': start_date.isoformat(),
            'end': end_date.isoformat(),
            'total_dates': total_dates,
        },
        'summary': {
            'dates': {
                'complete': dates_complete,
                'partial': dates_partial,
                'missing': dates_missing,
                'complete_pct': round(dates_complete / total_dates * 100, 1) if total_dates > 0 else 0,
            },
            'chains': {
                'total_checks': total_chain_checks,
                'complete': total_chains_complete,
                'partial': total_chains_partial,
                'missing': total_chains_missing,
                'complete_pct': round(total_chains_complete / total_chain_checks * 100, 1) if total_chain_checks > 0 else 0,
            },
            'phases': phase_stats,
            'backfill_status': 'complete' if dates_complete == total_dates else (
                'in_progress' if dates_complete > 0 else 'not_started'
            ),
        },
        'dates': [],
    }

    # Add per-date details
    for r in chain_results:
        date_data = {
            'date': r.game_date.isoformat(),
            'status': 'complete' if r.chains_complete == r.total_chains else (
                'partial' if r.chains_complete > 0 else 'missing'
            ),
            'chains': {
                'complete': r.chains_complete,
                'partial': r.chains_partial,
                'missing': r.chains_missing,
                'total': r.total_chains,
            },
        }

        # Add phase statuses if available
        if hasattr(r, 'phase_statuses'):
            date_data['phases'] = r.phase_statuses

        # Add fallback info if available
        if hasattr(r, 'fallbacks_used') and r.fallbacks_used:
            date_data['fallbacks_used'] = r.fallbacks_used

        output['dates'].append(date_data)

    if pretty:
        return json.dumps(output, indent=2, default=str)
    else:
        return json.dumps(output, default=str)


def format_combined_json(
    report,
    chain_validations: Dict[str, Any] = None,
    maintenance: Any = None,
    pretty: bool = True,
) -> str:
    """
    Format combined validation report with chain view as JSON.

    Args:
        report: ValidationReport (for phases 3-5 and context)
        chain_validations: Optional chain validations (for phases 1-2)
        maintenance: Optional maintenance validation
        pretty: Whether to pretty-print

    Returns:
        JSON string
    """
    # Start with standard report
    output = json.loads(format_validation_json(report, pretty=False))

    # Add chain validation data if provided
    if chain_validations:
        chain_data = json.loads(format_chain_validation_json(
            chain_validations, maintenance, pretty=False
        ))
        output['data_source_chains'] = chain_data['chains']
        output['chain_summary'] = chain_data['summary']
        if 'maintenance' in chain_data:
            output['maintenance'] = chain_data['maintenance']

    if pretty:
        return json.dumps(output, indent=2, default=str)
    else:
        return json.dumps(output, default=str)
