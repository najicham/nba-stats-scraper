#!/usr/bin/env python3
"""
Player linker for news articles.

Links extracted player names to our player registry system.
Uses fuzzy matching and team context to resolve ambiguous names.
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple
from functools import lru_cache

from fuzzywuzzy import fuzz

logger = logging.getLogger(__name__)


@dataclass
class LinkedPlayer:
    """A player mention linked to our registry."""
    name_as_written: str  # Original text from article
    player_lookup: Optional[str]  # Our registry ID (e.g., "lebronjames")
    player_name: Optional[str]  # Display name from registry
    universal_id: Optional[str]  # Universal player ID
    team_abbr: Optional[str]  # Current team
    confidence: float  # Link confidence 0-1
    link_method: str  # How we linked: 'exact', 'fuzzy', 'search', 'unlinked'

    def to_dict(self) -> dict:
        return {
            'name_as_written': self.name_as_written,
            'player_lookup': self.player_lookup,
            'player_name': self.player_name,
            'universal_id': self.universal_id,
            'team_abbr': self.team_abbr,
            'confidence': self.confidence,
            'link_method': self.link_method,
        }


class PlayerLinker:
    """
    Links player names from news articles to our registry.

    Uses multiple strategies:
    1. Exact match on normalized name
    2. Fuzzy match with high threshold
    3. Registry search with team context

    Usage:
        linker = PlayerLinker(sport='nba')
        linked = linker.link_player("LeBron James", team_context="LAL")
    """

    def __init__(self, sport: str = 'nba', season: str = '2025-26'):
        """
        Initialize player linker.

        Args:
            sport: 'nba' or 'mlb'
            season: Current season for registry queries
        """
        self.sport = sport
        self.season = season
        self._registry = None
        self._cache: Dict[str, LinkedPlayer] = {}

        logger.info(f"Initialized PlayerLinker for {sport} {season}")

    @property
    def registry(self):
        """Lazy load registry reader."""
        if self._registry is None:
            if self.sport == 'nba':
                from shared.utils.player_registry.reader import RegistryReader
                self._registry = RegistryReader(
                    source_name='news_player_linker',
                    cache_ttl_seconds=300  # 5 minute cache
                )
            else:
                # MLB registry - use MLB-specific reader if available
                try:
                    from shared.utils.player_registry.mlb_reader import MLBRegistryReader
                    self._registry = MLBRegistryReader(
                        source_name='news_player_linker',
                        cache_ttl_seconds=300
                    )
                except ImportError:
                    logger.warning("MLB registry reader not available, using NBA reader")
                    from shared.utils.player_registry.reader import RegistryReader
                    self._registry = RegistryReader(
                        source_name='news_player_linker',
                        cache_ttl_seconds=300
                    )
        return self._registry

    def link_player(
        self,
        name: str,
        team_context: Optional[str] = None
    ) -> LinkedPlayer:
        """
        Link a player name to our registry.

        Args:
            name: Player name from article (e.g., "LeBron James")
            team_context: Optional team abbreviation for disambiguation

        Returns:
            LinkedPlayer with registry info if found
        """
        # Check cache first
        cache_key = f"{name.lower()}:{team_context or ''}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Try linking strategies in order
        result = self._try_exact_match(name)
        if result.player_lookup:
            self._cache[cache_key] = result
            return result

        result = self._try_search_match(name, team_context)
        if result.player_lookup:
            self._cache[cache_key] = result
            return result

        # Return unlinked
        result = LinkedPlayer(
            name_as_written=name,
            player_lookup=None,
            player_name=None,
            universal_id=None,
            team_abbr=team_context,
            confidence=0.0,
            link_method='unlinked'
        )
        self._cache[cache_key] = result
        return result

    def _normalize_name(self, name: str) -> str:
        """Normalize name to player_lookup format."""
        # Remove suffixes
        name = re.sub(r'\s+(Jr\.?|Sr\.?|II|III|IV)$', '', name, flags=re.IGNORECASE)
        # Remove punctuation and spaces, lowercase
        normalized = re.sub(r'[^a-zA-Z]', '', name).lower()
        return normalized

    def _try_exact_match(self, name: str) -> LinkedPlayer:
        """Try exact match on normalized name."""
        normalized = self._normalize_name(name)

        try:
            player = self.registry.get_player(normalized, season=self.season)
            if player:
                return LinkedPlayer(
                    name_as_written=name,
                    player_lookup=player.get('player_lookup'),
                    player_name=player.get('player_name'),
                    universal_id=player.get('universal_player_id'),
                    team_abbr=player.get('team_abbr'),
                    confidence=1.0,
                    link_method='exact'
                )
        except Exception as e:
            logger.debug(f"Exact match failed for {name}: {e}")

        return LinkedPlayer(
            name_as_written=name,
            player_lookup=None,
            player_name=None,
            universal_id=None,
            team_abbr=None,
            confidence=0.0,
            link_method='unlinked'
        )

    def _try_search_match(
        self,
        name: str,
        team_context: Optional[str] = None
    ) -> LinkedPlayer:
        """Try registry search with fuzzy matching."""
        try:
            # Search registry
            results = self.registry.search_players(name, season=self.season, limit=5)

            if not results:
                return LinkedPlayer(
                    name_as_written=name,
                    player_lookup=None,
                    player_name=None,
                    universal_id=None,
                    team_abbr=team_context,
                    confidence=0.0,
                    link_method='unlinked'
                )

            # Score results
            best_match = None
            best_score = 0

            for result in results:
                player_name = result.get('player_name', '')
                score = fuzz.ratio(name.lower(), player_name.lower())

                # Boost score if team matches
                if team_context and result.get('team_abbr') == team_context:
                    score += 15

                if score > best_score:
                    best_score = score
                    best_match = result

            # Only accept high-confidence matches
            if best_score >= 85:
                confidence = min(best_score / 100, 0.95)
                return LinkedPlayer(
                    name_as_written=name,
                    player_lookup=best_match.get('player_lookup'),
                    player_name=best_match.get('player_name'),
                    universal_id=best_match.get('universal_player_id'),
                    team_abbr=best_match.get('team_abbr'),
                    confidence=confidence,
                    link_method='search'
                )

        except Exception as e:
            logger.debug(f"Search match failed for {name}: {e}")

        return LinkedPlayer(
            name_as_written=name,
            player_lookup=None,
            player_name=None,
            universal_id=None,
            team_abbr=team_context,
            confidence=0.0,
            link_method='unlinked'
        )

    def link_players_batch(
        self,
        player_mentions: List[dict],
        team_context: Optional[List[str]] = None
    ) -> List[LinkedPlayer]:
        """
        Link multiple player mentions.

        Args:
            player_mentions: List of {'name': str, ...} dicts
            team_context: Optional list of team abbreviations from article

        Returns:
            List of LinkedPlayer results
        """
        results = []
        teams = team_context or []

        for mention in player_mentions:
            name = mention.get('name') or mention.get('name_as_written', '')
            if not name:
                continue

            # Use first team as context if available
            team = teams[0] if teams else None
            linked = self.link_player(name, team_context=team)
            results.append(linked)

        return results

    def get_stats(self) -> dict:
        """Get linking statistics."""
        if not self._cache:
            return {'total': 0, 'linked': 0, 'unlinked': 0}

        total = len(self._cache)
        linked = sum(1 for p in self._cache.values() if p.player_lookup)
        methods = {}
        for p in self._cache.values():
            methods[p.link_method] = methods.get(p.link_method, 0) + 1

        return {
            'total': total,
            'linked': linked,
            'unlinked': total - linked,
            'link_rate': linked / total if total > 0 else 0,
            'by_method': methods,
        }


def test_linker():
    """Test the player linker."""
    logging.basicConfig(level=logging.INFO)

    linker = PlayerLinker(sport='nba', season='2025-26')

    test_names = [
        ("LeBron James", "LAL"),
        ("Giannis Antetokounmpo", "MIL"),
        ("Trae Young", "ATL"),
        ("Anthony Davis", "LAL"),
        ("Stephen Curry", "GSW"),
        ("Cooper Flagg", None),  # Rookie
        ("Fake Player Name", None),  # Should not match
    ]

    print("\n" + "="*60)
    print("  Player Linker Test")
    print("="*60 + "\n")

    for name, team in test_names:
        result = linker.link_player(name, team_context=team)
        status = "LINKED" if result.player_lookup else "UNLINKED"
        print(f"{name}")
        print(f"  Status: {status}")
        print(f"  Lookup: {result.player_lookup}")
        print(f"  Method: {result.link_method}")
        print(f"  Confidence: {result.confidence:.0%}")
        print()

    print("Stats:", linker.get_stats())


if __name__ == '__main__':
    test_linker()
