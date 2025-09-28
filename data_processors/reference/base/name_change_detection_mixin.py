#!/usr/bin/env python3
"""
File: data_processors/reference/base/name_change_detection_mixin.py

Mixin for enhanced name change detection capabilities.
Provides investigation and similarity analysis for potential player name changes.
"""

import json
import logging
import re
from datetime import datetime, date
from typing import Dict, List
from difflib import SequenceMatcher
from google.cloud import bigquery, storage

logger = logging.getLogger(__name__)


class NameChangeDetectionMixin:
    """
    Mixin class providing enhanced name change detection capabilities.
    
    This mixin adds investigation functionality to registry processors:
    - Detailed alias checking with analysis results
    - Player similarity analysis for potential name changes
    - Confidence scoring for investigation prioritization
    - Structured investigation report generation
    - Evidence collection and human-readable summaries
    """
    
    def _check_player_aliases_detailed(self, player_lookup: str, team_abbr: str) -> Dict:
        """Enhanced alias checking with detailed results."""
        alias_query = f"""
        SELECT 
            r.player_lookup, 
            r.team_abbr, 
            r.games_played,
            a.alias_lookup,
            a.nba_canonical_lookup
        FROM `{self.project_id}.{self.alias_table_name}` a
        JOIN `{self.project_id}.{self.table_name}` r
        ON a.nba_canonical_lookup = r.player_lookup
        WHERE a.alias_lookup = @alias_lookup
        AND r.team_abbr = @team_abbr
        AND a.is_active = TRUE
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("alias_lookup", "STRING", player_lookup),
            bigquery.ScalarQueryParameter("team_abbr", "STRING", team_abbr)
        ])
        
        try:
            results = self.bq_client.query(alias_query, job_config=job_config).to_dataframe()
            
            if not results.empty:
                canonical_name = results.iloc[0]['nba_canonical_lookup']
                games_played = results.iloc[0]['games_played']
                
                return {
                    'found': True,
                    'canonical_name': canonical_name,
                    'games_played': games_played,
                    'resolution_method': 'alias_mapping'
                }
            else:
                return {
                    'found': False,
                    'resolution_method': 'none'
                }
                
        except Exception as e:
            logger.warning(f"Error checking player aliases: {e}")
            return {
                'found': False,
                'resolution_method': 'error',
                'error': str(e)
            }

    def _create_enhanced_investigation(self, player_lookup: str, team_abbr: str, 
                                     enhancement: Dict, alias_check: Dict) -> Dict:
        """Create detailed investigation record with similarity analysis."""
        
        # Get recent players from same team for similarity comparison
        recent_players = self._get_recent_team_players(team_abbr)
        
        # Find similar names
        similar_players = []
        for recent_player in recent_players:
            similarity = self._calculate_name_similarity(player_lookup, recent_player['player_lookup'])
            if similarity > 0.6:
                similar_players.append({
                    'player_lookup': recent_player['player_lookup'],
                    'similarity_score': similarity,
                    'last_game_date': recent_player['last_game_date'],
                    'games_played': recent_player['games_played']
                })
        
        # Sort by similarity
        similar_players.sort(key=lambda x: x['similarity_score'], reverse=True)
        
        # Calculate confidence score
        confidence_score = self._calculate_confidence_score(
            player_lookup, similar_players, enhancement
        )
        
        # Generate evidence notes
        evidence_notes = self._generate_evidence_notes(
            player_lookup, similar_players, enhancement, alias_check
        )
        
        return {
            'new_player_lookup': player_lookup,
            'team_abbr': team_abbr,
            'original_name': enhancement.get('original_name', 'Unknown'),
            'jersey_number': enhancement.get('jersey_number'),
            'position': enhancement.get('position'),
            'similar_existing_players': similar_players[:3],  # Top 3 matches
            'confidence_score': confidence_score,
            'evidence_notes': evidence_notes,
            'alias_check_result': alias_check,
            'detection_method': 'basketball_reference_registry_comparison'
        }

    def _get_recent_team_players(self, team_abbr: str, seasons: int = 2) -> List[Dict]:
        """Get recent players from the same team."""
        query = f"""
        SELECT 
            player_lookup,
            player_name,
            MAX(last_game_date) as last_game_date,
            SUM(games_played) as games_played
        FROM `{self.project_id}.{self.table_name}`
        WHERE team_abbr = @team_abbr
        AND EXTRACT(YEAR FROM last_game_date) >= EXTRACT(YEAR FROM CURRENT_DATE()) - @seasons
        GROUP BY player_lookup, player_name
        ORDER BY last_game_date DESC
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("team_abbr", "STRING", team_abbr),
            bigquery.ScalarQueryParameter("seasons", "INT64", seasons)
        ])
        
        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            return results.to_dict('records')
        except Exception as e:
            logger.warning(f"Error getting recent team players: {e}")
            return []

    def _calculate_name_similarity(self, name1: str, name2: str) -> float:
        """Calculate similarity between two player names.""" 
        
        # Normalize names for comparison
        def normalize_name(name):
            normalized = name.lower().strip()
            # Remove common suffixes/prefixes
            normalized = re.sub(r'\b(jr|sr|ii|iii|iv)\b', '', normalized)
            # Remove special characters
            normalized = re.sub(r'[^a-z\s]', '', normalized)
            # Remove extra spaces
            normalized = re.sub(r'\s+', ' ', normalized).strip()
            return normalized
        
        norm1 = normalize_name(name1)
        norm2 = normalize_name(name2)
        
        return SequenceMatcher(None, norm1, norm2).ratio()

    def _calculate_confidence_score(self, new_player: str, similar_players: List[Dict], 
                                  enhancement: Dict) -> float:
        """Calculate confidence that this is a name change (0.0-1.0 scale)."""
        score = 0.0
        
        # High similarity match bonuses
        if similar_players and similar_players[0]['similarity_score'] > 0.8:
            score += 0.6
        elif similar_players and similar_players[0]['similarity_score'] > 0.6:
            score += 0.4
        
        # Recent activity bonus
        if similar_players:
            for player in similar_players:
                if (player['last_game_date'] and 
                    (date.today() - player['last_game_date']).days < 365):
                    score += 0.3
                    break
        
        # Pattern detection bonuses
        if 'jr' in new_player.lower() or 'sr' in new_player.lower():
            score += 0.2  # Generational suffix changes are common
        
        if enhancement.get('jersey_number'):
            score += 0.1  # Having jersey info increases confidence
        
        if len(similar_players) > 1 and similar_players[1]['similarity_score'] > 0.6:
            score += 0.1  # Multiple similar matches
            
        return min(score, 1.0)

    def _generate_evidence_notes(self, new_player: str, similar_players: List[Dict], 
                               enhancement: Dict, alias_check: Dict) -> str:
        """Generate human-readable evidence notes for manual review."""
        notes = []
        
        # Alias information
        if alias_check['found']:
            notes.append(f"Already resolved via alias to: {alias_check['canonical_name']}")
        
        # Similarity analysis
        if similar_players:
            top_match = similar_players[0]
            notes.append(f"Most similar to '{top_match['player_lookup']}' (similarity: {top_match['similarity_score']:.2f})")
            
            if top_match['last_game_date']:
                days_ago = (date.today() - top_match['last_game_date']).days
                notes.append(f"Similar player last played {days_ago} days ago")
        
        # Enhancement data
        if enhancement.get('jersey_number'):
            notes.append(f"Jersey #{enhancement['jersey_number']}")
            
        if enhancement.get('position'):
            notes.append(f"Position: {enhancement['position']}")
        
        # Pattern detection
        if 'jr' in new_player.lower() or 'sr' in new_player.lower():
            notes.append("Contains generational suffix")
            
        if len(new_player.split()) == 1:
            notes.append("Single name - check for nickname adoption")
        
        return '; '.join(notes) if notes else "No obvious patterns detected"

    def _save_investigation_report(self, investigation_report: Dict):
        """Save investigation report to GCS for manual review."""
        try:
            storage_client = storage.Client()
            
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            processor_type = investigation_report.get('processor_type', 'unknown_processor')
            filename = f"name_change_investigations/{processor_type}/{timestamp}_investigation_report.json"
            
            # Add metadata for easier processing
            investigation_report['report_metadata'] = {
                'generated_at': datetime.utcnow().isoformat(),
                'filename': filename,
                'requires_manual_review': investigation_report.get('total_investigations', 0) > 0,
                'high_confidence_count': len([
                    inv for inv in investigation_report.get('investigations', []) 
                    if inv.get('confidence_score', 0) > 0.7
                ])
            }
            
            bucket = storage_client.bucket('nba-props-platform-investigations')
            blob = bucket.blob(filename)
            
            blob.upload_from_string(
                json.dumps(investigation_report, indent=2),
                content_type='application/json'
            )
            
            logger.info(f"Investigation report saved: gs://nba-props-platform-investigations/{filename}")
            
            # Log summary for operational awareness
            total_investigations = investigation_report.get('total_investigations', 0)
            high_confidence = investigation_report['report_metadata']['high_confidence_count']
            
            if total_investigations > 0:
                logger.info(f"🔍 Generated {total_investigations} investigations ({high_confidence} high-confidence)")
                if high_confidence > 0:
                    logger.info("⚠️  High-confidence cases require immediate manual review")
            
        except Exception as e:
            logger.warning(f"Could not save investigation report: {e}")
            # Don't fail the whole process for investigation report issues

    def _get_investigation_bucket_name(self) -> str:
        """Get the GCS bucket name for investigation reports."""
        return 'nba-props-platform-investigations'

    def _should_investigate_player(self, player_lookup: str, confidence_threshold: float = 0.3) -> bool:
        """Determine if a player warrants investigation based on patterns."""
        
        # Always investigate if similarity analysis would be meaningful
        if len(player_lookup) > 3:  # Avoid very short names
            return True
            
        # Skip investigation for obviously different players
        skip_patterns = [
            r'^[a-z]+\d+$',  # Names with numbers (e.g., 'player1')
            r'^test[a-z]*$',  # Test players
        ]
        
        for pattern in skip_patterns:
            if re.match(pattern, player_lookup.lower()):
                logger.debug(f"Skipping investigation for {player_lookup} - matches skip pattern")
                return False
        
        return True
    