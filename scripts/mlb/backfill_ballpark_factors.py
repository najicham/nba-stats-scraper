#!/usr/bin/env python3
"""Load 2025+2026 ballpark factors into mlb_reference.ballpark_factors.

Usage:
    PYTHONPATH=. .venv/bin/python scripts/mlb/backfill_ballpark_factors.py
"""

import hashlib
from datetime import datetime, timezone

from google.cloud import bigquery

PROJECT_ID = 'nba-props-platform'
TABLE_ID = f'{PROJECT_ID}.mlb_reference.ballpark_factors'

# Static ballpark factors (2024-2025 estimates from FanGraphs/Baseball Reference)
# k_factor: >100 = more Ks, <100 = fewer Ks
PARKS = {
    # (venue_name, team_name, k_factor, runs_factor, hr_factor, elevation, is_dome, is_retractable, surface)
    'BAL': ('Oriole Park at Camden Yards', 'Orioles', 98, 102, 108, 33, False, False, 'grass'),
    'BOS': ('Fenway Park', 'Red Sox', 96, 106, 104, 21, False, False, 'grass'),
    'NYY': ('Yankee Stadium', 'Yankees', 100, 104, 112, 55, False, False, 'grass'),
    'TB':  ('Tropicana Field', 'Rays', 102, 96, 94, 43, True, False, 'turf'),
    'TOR': ('Rogers Centre', 'Blue Jays', 99, 100, 102, 269, False, True, 'turf'),
    'CLE': ('Progressive Field', 'Guardians', 101, 97, 96, 653, False, False, 'grass'),
    'CWS': ('Guaranteed Rate Field', 'White Sox', 99, 101, 105, 595, False, False, 'grass'),
    'DET': ('Comerica Park', 'Tigers', 103, 95, 92, 600, False, False, 'grass'),
    'KC':  ('Kauffman Stadium', 'Royals', 100, 98, 96, 889, False, False, 'grass'),
    'MIN': ('Target Field', 'Twins', 100, 99, 98, 841, False, False, 'grass'),
    'HOU': ('Minute Maid Park', 'Astros', 98, 103, 108, 43, False, True, 'grass'),
    'LAA': ('Angel Stadium', 'Angels', 99, 98, 98, 160, False, False, 'grass'),
    'OAK': ('Oakland Coliseum', 'Athletics', 104, 93, 90, 39, False, False, 'grass'),
    'SEA': ('T-Mobile Park', 'Mariners', 103, 94, 92, 20, False, True, 'grass'),
    'TEX': ('Globe Life Field', 'Rangers', 101, 98, 98, 551, False, True, 'grass'),
    'ATL': ('Truist Park', 'Braves', 99, 100, 102, 1050, False, False, 'grass'),
    'MIA': ('loanDepot park', 'Marlins', 102, 96, 93, 7, False, True, 'grass'),
    'NYM': ('Citi Field', 'Mets', 105, 94, 91, 20, False, False, 'grass'),
    'PHI': ('Citizens Bank Park', 'Phillies', 97, 105, 110, 20, False, False, 'grass'),
    'WSH': ('Nationals Park', 'Nationals', 100, 99, 100, 25, False, False, 'grass'),
    'CHC': ('Wrigley Field', 'Cubs', 98, 102, 104, 600, False, False, 'grass'),
    'CIN': ('Great American Ball Park', 'Reds', 94, 108, 115, 490, False, False, 'grass'),
    'MIL': ('American Family Field', 'Brewers', 100, 100, 102, 635, False, True, 'grass'),
    'PIT': ('PNC Park', 'Pirates', 102, 96, 93, 730, False, False, 'grass'),
    'STL': ('Busch Stadium', 'Cardinals', 99, 98, 97, 455, False, False, 'grass'),
    'AZ':  ('Chase Field', 'Diamondbacks', 98, 104, 106, 1082, False, True, 'grass'),
    'COL': ('Coors Field', 'Rockies', 88, 118, 120, 5280, False, False, 'grass'),
    'LAD': ('Dodger Stadium', 'Dodgers', 101, 97, 96, 512, False, False, 'grass'),
    'SD':  ('Petco Park', 'Padres', 106, 92, 88, 22, False, False, 'grass'),
    'SF':  ('Oracle Park', 'Giants', 105, 93, 86, 2, False, False, 'grass'),
}


def main():
    client = bigquery.Client(project=PROJECT_ID)
    now_str = datetime.now(timezone.utc).isoformat()

    rows = []
    for season in [2025, 2026]:
        for abbr, (name, team, k, run, hr, alt, dome, retract, surface) in PARKS.items():
            row_str = f'{season}|{abbr}|{k}|{run}|{hr}'
            rows.append({
                'season_year': season,
                'venue_name': name,
                'team_abbr': abbr,
                'team_name': team,
                'overall_factor': 100,
                'runs_factor': run,
                'home_runs_factor': hr,
                'hits_factor': 100,
                'doubles_factor': 100,
                'triples_factor': 100,
                'strikeouts_factor': k,
                'walks_factor': 100,
                'elevation_feet': alt,
                'fence_distance_lf': 330,
                'fence_distance_cf': 400,
                'fence_distance_rf': 330,
                'is_dome': dome,
                'is_retractable_roof': retract,
                'surface_type': surface,
                'source': 'FanGraphs/Baseball Reference (compiled)',
                'data_hash': hashlib.md5(row_str.encode()).hexdigest(),
                'created_at': now_str,
                'updated_at': now_str,
            })

    # Delete existing
    print("Deleting existing 2025-2026 rows...")
    client.query(
        f'DELETE FROM `{TABLE_ID}` WHERE season_year IN (2025, 2026)'
    ).result(timeout=30)

    # Load
    print(f"Loading {len(rows)} rows...")
    table = client.get_table(TABLE_ID)
    job = client.load_table_from_json(
        rows, TABLE_ID,
        job_config=bigquery.LoadJobConfig(
            schema=table.schema,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        )
    )
    job.result(timeout=60)
    print(f"Loaded {len(rows)} ballpark factors (30 teams x 2 seasons)")

    # Verify
    result = client.query(
        f'SELECT season_year, COUNT(*) as cnt FROM `{TABLE_ID}` GROUP BY 1 ORDER BY 1'
    ).result()
    for row in result:
        print(f"  Season {row.season_year}: {row.cnt} teams")


if __name__ == '__main__':
    main()
