#!/usr/bin/env python3
"""
GCS-Only Backup Scrapers

These scrapers store data to GCS for emergency use only.
NOT stored in BigQuery - just archived as JSON for if we need them.

Sources:
- nba_api: Schedule, Standings, Rosters, Advanced Stats
- Basketball Reference: Season totals, Advanced, Standings

Created: 2026-01-28
"""

import json
import logging
import os
import time
from datetime import date, datetime, timezone
from typing import Any, Dict, List

from google.cloud import storage

logger = logging.getLogger(__name__)

# Rate limiting
REQUEST_DELAY = 1.0


class GCSBackupBase:
    """Base class for GCS-only backup scrapers."""

    def __init__(self, project_id: str = None, bucket_name: str = None):
        self.project_id = project_id or os.environ.get('GCP_PROJECT', 'nba-props-platform')
        self.bucket_name = bucket_name or f"{self.project_id}-backup-data"
        self.gcs_client = storage.Client(project=self.project_id)

    def save_to_gcs(self, data: Any, path: str) -> bool:
        """Save data to GCS as JSON."""
        try:
            bucket = self.gcs_client.bucket(self.bucket_name)
            blob = bucket.blob(path)

            json_data = json.dumps(data, indent=2, default=str)
            blob.upload_from_string(json_data, content_type='application/json')

            logger.info(f"Saved to gs://{self.bucket_name}/{path}")
            return True
        except Exception as e:
            logger.error(f"Error saving to GCS: {e}")
            return False


class NBAApiScheduleScraper(GCSBackupBase):
    """Scrape NBA schedule as backup."""

    def scrape(self, season: str = None) -> Dict:
        """Scrape full season schedule."""
        from nba_api.stats.endpoints import LeagueGameLog

        if season is None:
            # Current season format: "2025-26"
            year = date.today().year
            month = date.today().month
            if month >= 10:
                season = f"{year}-{str(year+1)[2:]}"
            else:
                season = f"{year-1}-{str(year)[2:]}"

        logger.info(f"Scraping schedule for {season}")
        time.sleep(REQUEST_DELAY)

        try:
            game_log = LeagueGameLog(
                season=season,
                season_type_all_star='Regular Season'
            )
            data = game_log.get_dict()

            result = {
                'season': season,
                'scraped_at': datetime.now(timezone.utc).isoformat(),
                'data': data
            }

            path = f"nba_api/schedule/{season}/{date.today().isoformat()}.json"
            self.save_to_gcs(result, path)

            return {'success': True, 'games': len(data.get('resultSets', [{}])[0].get('rowSet', []))}
        except Exception as e:
            logger.error(f"Error scraping schedule: {e}")
            return {'success': False, 'error': str(e)}


class NBAApiStandingsScraper(GCSBackupBase):
    """Scrape NBA standings as backup."""

    def scrape(self, season: str = None) -> Dict:
        """Scrape current standings."""
        from nba_api.stats.endpoints import LeagueStandingsV3

        logger.info("Scraping standings")
        time.sleep(REQUEST_DELAY)

        try:
            standings = LeagueStandingsV3(
                league_id='00',
                season=season or '2025-26',
                season_type='Regular Season'
            )
            data = standings.get_dict()

            result = {
                'scraped_at': datetime.now(timezone.utc).isoformat(),
                'data': data
            }

            path = f"nba_api/standings/{date.today().isoformat()}.json"
            self.save_to_gcs(result, path)

            return {'success': True}
        except Exception as e:
            logger.error(f"Error scraping standings: {e}")
            return {'success': False, 'error': str(e)}


class NBAApiRosterScraper(GCSBackupBase):
    """Scrape all team rosters as backup."""

    def scrape(self, season: str = None) -> Dict:
        """Scrape all team rosters."""
        from nba_api.stats.endpoints import CommonTeamRoster
        from nba_api.stats.static import teams

        logger.info("Scraping all team rosters")

        all_rosters = {}
        nba_teams = teams.get_teams()

        for team in nba_teams:
            try:
                time.sleep(REQUEST_DELAY)
                roster = CommonTeamRoster(
                    team_id=team['id'],
                    season=season or '2025-26'
                )
                all_rosters[team['abbreviation']] = roster.get_dict()
            except Exception as e:
                logger.warning(f"Error scraping {team['abbreviation']}: {e}")

        result = {
            'scraped_at': datetime.now(timezone.utc).isoformat(),
            'rosters': all_rosters
        }

        path = f"nba_api/rosters/{date.today().isoformat()}.json"
        self.save_to_gcs(result, path)

        return {'success': True, 'teams': len(all_rosters)}


class BRefSeasonTotalsScraper(GCSBackupBase):
    """Scrape Basketball Reference season totals."""

    def scrape(self, season_end_year: int = None) -> Dict:
        """Scrape season totals for all players."""
        from basketball_reference_web_scraper import client

        if season_end_year is None:
            season_end_year = date.today().year if date.today().month >= 10 else date.today().year

        logger.info(f"Scraping BRef season totals for {season_end_year}")
        time.sleep(3)  # Longer delay for BRef

        try:
            players = client.players_season_totals(season_end_year=season_end_year)

            # Convert enums to strings
            processed = []
            for p in players:
                row = {}
                for k, v in p.items():
                    if hasattr(v, 'name'):
                        row[k] = v.name
                    elif hasattr(v, 'value'):
                        row[k] = v.value
                    else:
                        row[k] = v
                processed.append(row)

            result = {
                'season_end_year': season_end_year,
                'scraped_at': datetime.now(timezone.utc).isoformat(),
                'players': processed
            }

            path = f"basketball_reference/season_totals/{season_end_year}/{date.today().isoformat()}.json"
            self.save_to_gcs(result, path)

            return {'success': True, 'players': len(processed)}
        except Exception as e:
            logger.error(f"Error scraping BRef season totals: {e}")
            return {'success': False, 'error': str(e)}


class BRefAdvancedStatsScraper(GCSBackupBase):
    """Scrape Basketball Reference advanced stats."""

    def scrape(self, season_end_year: int = None) -> Dict:
        """Scrape advanced stats for all players."""
        from basketball_reference_web_scraper import client

        if season_end_year is None:
            season_end_year = date.today().year if date.today().month >= 10 else date.today().year

        logger.info(f"Scraping BRef advanced stats for {season_end_year}")
        time.sleep(3)

        try:
            players = client.players_advanced_season_totals(season_end_year=season_end_year)

            # Convert enums to strings
            processed = []
            for p in players:
                row = {}
                for k, v in p.items():
                    if hasattr(v, 'name'):
                        row[k] = v.name
                    elif hasattr(v, 'value'):
                        row[k] = v.value
                    else:
                        row[k] = v
                processed.append(row)

            result = {
                'season_end_year': season_end_year,
                'scraped_at': datetime.now(timezone.utc).isoformat(),
                'players': processed
            }

            path = f"basketball_reference/advanced_stats/{season_end_year}/{date.today().isoformat()}.json"
            self.save_to_gcs(result, path)

            return {'success': True, 'players': len(processed)}
        except Exception as e:
            logger.error(f"Error scraping BRef advanced stats: {e}")
            return {'success': False, 'error': str(e)}


class BRefStandingsScraper(GCSBackupBase):
    """Scrape Basketball Reference standings."""

    def scrape(self, season_end_year: int = None) -> Dict:
        """Scrape current standings."""
        from basketball_reference_web_scraper import client

        if season_end_year is None:
            season_end_year = date.today().year + 1 if date.today().month >= 10 else date.today().year

        logger.info(f"Scraping BRef standings for {season_end_year}")
        time.sleep(3)

        try:
            standings = client.standings(season_end_year=season_end_year)

            # Convert enums
            processed = []
            for team in standings:
                row = {}
                for k, v in team.items():
                    if hasattr(v, 'name'):
                        row[k] = v.name
                    elif hasattr(v, 'value'):
                        row[k] = v.value
                    else:
                        row[k] = v
                processed.append(row)

            result = {
                'season_end_year': season_end_year,
                'scraped_at': datetime.now(timezone.utc).isoformat(),
                'standings': processed
            }

            path = f"basketball_reference/standings/{date.today().isoformat()}.json"
            self.save_to_gcs(result, path)

            return {'success': True, 'teams': len(processed)}
        except Exception as e:
            logger.error(f"Error scraping BRef standings: {e}")
            return {'success': False, 'error': str(e)}


def run_all_gcs_backups():
    """Run all GCS backup scrapers."""
    logging.basicConfig(level=logging.INFO)

    results = {}

    # NBA API scrapers
    results['nba_api_schedule'] = NBAApiScheduleScraper().scrape()
    results['nba_api_standings'] = NBAApiStandingsScraper().scrape()
    results['nba_api_rosters'] = NBAApiRosterScraper().scrape()

    # Basketball Reference scrapers
    results['bref_season_totals'] = BRefSeasonTotalsScraper().scrape()
    results['bref_advanced_stats'] = BRefAdvancedStatsScraper().scrape()
    results['bref_standings'] = BRefStandingsScraper().scrape()

    print("\n=== GCS Backup Results ===")
    for name, result in results.items():
        status = "✅" if result.get('success') else "❌"
        print(f"{status} {name}: {result}")

    return results


if __name__ == '__main__':
    run_all_gcs_backups()
