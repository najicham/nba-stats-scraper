#!/usr/bin/env python3
"""
Keyword and entity extraction from news articles.

Extracts:
1. News category (injury, trade, lineup, etc.)
2. Player names mentioned
3. Team mentions
4. Key facts

This is a simple regex-based extractor - no AI required.
"""

import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Set, Dict, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class NewsCategory(str, Enum):
    """Categories of sports news."""
    INJURY = "injury"
    TRADE = "trade"
    LINEUP = "lineup"
    SIGNING = "signing"
    SUSPENSION = "suspension"
    PERFORMANCE = "performance"
    PREVIEW = "preview"
    RECAP = "recap"
    ANALYSIS = "analysis"
    OTHER = "other"


@dataclass
class ExtractedMention:
    """A player name mention extracted from text."""
    name_as_written: str  # Exact text found
    likely_full_name: str  # Best guess at full name
    position_in_text: int  # Character position
    context: str  # Surrounding text
    confidence: float  # 0-1 confidence score


@dataclass
class ExtractionResult:
    """Result of extracting information from an article."""
    article_id: str

    # Classification
    category: NewsCategory
    subcategory: Optional[str]  # e.g., "questionable", "out", "trade_rumor"
    confidence: float

    # Entities
    player_mentions: List[ExtractedMention] = field(default_factory=list)
    teams_mentioned: List[str] = field(default_factory=list)

    # Keywords found
    keywords_matched: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            'article_id': self.article_id,
            'category': self.category.value,
            'subcategory': self.subcategory,
            'confidence': self.confidence,
            'player_mentions': [
                {
                    'name': m.name_as_written,
                    'full_name': m.likely_full_name,
                    'context': m.context,
                    'confidence': m.confidence
                }
                for m in self.player_mentions
            ],
            'teams_mentioned': self.teams_mentioned,
            'keywords_matched': self.keywords_matched,
        }


# Keyword patterns for categorization
CATEGORY_KEYWORDS = {
    NewsCategory.INJURY: [
        r'\b(injur\w+|hurt|sprain\w*|strain\w*|fractur\w*|concussion)',
        r'\b(out|doubtful|questionable|probable|day-to-day|DTD)',
        r'\b(IL|injured list|disabled list|DL)\b',
        r'\b(surgery|MRI|X-ray|CT scan)',
        r'\b(miss\w*|sidelin\w*|ruled out|will not play)',
        r'\b(return\w* from|back from|recover\w*)',
        r'\b(ankle|knee|hamstring|shoulder|back|wrist|foot|calf|groin|hip|quad)',
    ],
    NewsCategory.TRADE: [
        r'\b(trad\w+|dealt|acquir\w*|send\w* to|swap)',
        r'\b(trade deadline|trade rumor|trade talk)',
        r'\b(package|haul|return for)',
        r'\b(in exchange for|as part of)',
    ],
    NewsCategory.SIGNING: [
        r'\b(sign\w*|contract|deal|extension|free agen)',
        r'\b(agree\w* to|ink\w*|pen\w* deal)',
        r'\b(\$\d+[MKB]|\d+ year|\d+-year)',
        r'\b(guaranteed|option|player option|team option)',
    ],
    NewsCategory.LINEUP: [
        r'\b(start\w*|bench\w*|lineup|rotation)',
        r'\b(rest\w*|load manag\w*|DNP)',
        r'\b(will play|expected to play|cleared to play)',
        r'\b(active|inactive|scratch\w*)',
    ],
    NewsCategory.SUSPENSION: [
        r'\b(suspend\w*|ban\w*|fine\w*|eject\w*)',
        r'\b(disciplin\w*|violat\w*)',
        r'\b(game suspension|\d+ game\w* suspen)',
    ],
    NewsCategory.PERFORMANCE: [
        r'\b(score\w* \d+|point\w*|rebound\w*|assist\w*)',
        r'\b(triple-double|double-double|career-high)',
        r'\b(MVP|All-Star|Player of)',
        r'\b(streak|consecutive|in a row)',
    ],
    NewsCategory.PREVIEW: [
        r'\b(preview|matchup|face\w* off|take\w* on)',
        r'\b(tonight|tomorrow|upcoming)',
        r'\b(odds|spread|over/under|betting)',
    ],
    NewsCategory.RECAP: [
        r'\b(recap|beat\w*|defeat\w*|win\w* over|lose? to)',
        r'\b(final score|box score)',
        r'\b(last night|yesterday)',
    ],
}

# Injury subcategories
INJURY_SUBCATEGORIES = {
    'out': [r'\b(out|ruled out|will not play|miss\w*|sidelin)'],
    'doubtful': [r'\b(doubtful)'],
    'questionable': [r'\b(questionable|game-time decision)'],
    'probable': [r'\b(probable|likely to play|expected to play)'],
    'returning': [r'\b(return\w*|back from|cleared|activat)'],
}

# Trade subcategories
TRADE_SUBCATEGORIES = {
    'completed': [r'\b(traded|dealt|acquired|send\w* to)\b'],
    'rumor': [r'\b(rumor|could|might|may|interest\w* in|target\w*)'],
    'discussion': [r'\b(discuss\w*|talk\w*|explor\w*|consider\w*)'],
}

# NBA team patterns
NBA_TEAMS = {
    'ATL': ['hawks', 'atlanta'],
    'BOS': ['celtics', 'boston'],
    'BKN': ['nets', 'brooklyn'],
    'CHA': ['hornets', 'charlotte'],
    'CHI': ['bulls', 'chicago'],
    'CLE': ['cavaliers', 'cavs', 'cleveland'],
    'DAL': ['mavericks', 'mavs', 'dallas'],
    'DEN': ['nuggets', 'denver'],
    'DET': ['pistons', 'detroit'],
    'GSW': ['warriors', 'golden state', 'dubs'],
    'HOU': ['rockets', 'houston'],
    'IND': ['pacers', 'indiana'],
    'LAC': ['clippers', 'la clippers'],
    'LAL': ['lakers', 'la lakers', 'los angeles lakers'],
    'MEM': ['grizzlies', 'memphis'],
    'MIA': ['heat', 'miami'],
    'MIL': ['bucks', 'milwaukee'],
    'MIN': ['timberwolves', 'wolves', 'minnesota'],
    'NOP': ['pelicans', 'new orleans'],
    'NYK': ['knicks', 'new york'],
    'OKC': ['thunder', 'oklahoma city', 'okc'],
    'ORL': ['magic', 'orlando'],
    'PHI': ['76ers', 'sixers', 'philadelphia'],
    'PHX': ['suns', 'phoenix'],
    'POR': ['trail blazers', 'blazers', 'portland'],
    'SAC': ['kings', 'sacramento'],
    'SAS': ['spurs', 'san antonio'],
    'TOR': ['raptors', 'toronto'],
    'UTA': ['jazz', 'utah'],
    'WAS': ['wizards', 'washington'],
}

# MLB team patterns
MLB_TEAMS = {
    'ARI': ['diamondbacks', 'd-backs', 'arizona'],
    'ATL': ['braves', 'atlanta'],
    'BAL': ['orioles', 'o\'s', 'baltimore'],
    'BOS': ['red sox', 'boston'],
    'CHC': ['cubs', 'chicago cubs'],
    'CWS': ['white sox', 'chicago white sox'],
    'CIN': ['reds', 'cincinnati'],
    'CLE': ['guardians', 'cleveland'],
    'COL': ['rockies', 'colorado'],
    'DET': ['tigers', 'detroit'],
    'HOU': ['astros', 'houston'],
    'KC': ['royals', 'kansas city'],
    'LAA': ['angels', 'los angeles angels', 'la angels'],
    'LAD': ['dodgers', 'los angeles dodgers', 'la dodgers'],
    'MIA': ['marlins', 'miami'],
    'MIL': ['brewers', 'milwaukee'],
    'MIN': ['twins', 'minnesota'],
    'NYM': ['mets', 'new york mets'],
    'NYY': ['yankees', 'new york yankees'],
    'OAK': ['athletics', 'a\'s', 'oakland'],
    'PHI': ['phillies', 'philadelphia'],
    'PIT': ['pirates', 'pittsburgh'],
    'SD': ['padres', 'san diego'],
    'SF': ['giants', 'san francisco'],
    'SEA': ['mariners', 'seattle'],
    'STL': ['cardinals', 'st. louis', 'cards'],
    'TB': ['rays', 'tampa bay'],
    'TEX': ['rangers', 'texas'],
    'TOR': ['blue jays', 'jays', 'toronto'],
    'WSH': ['nationals', 'nats', 'washington'],
}


class KeywordExtractor:
    """
    Extracts keywords, categories, and entities from news articles.

    Usage:
        extractor = KeywordExtractor()
        result = extractor.extract(article_id, title, summary, sport='nba')
    """

    def __init__(self):
        """Initialize the extractor with compiled patterns."""
        # Compile category patterns
        self.category_patterns = {
            cat: [re.compile(p, re.IGNORECASE) for p in patterns]
            for cat, patterns in CATEGORY_KEYWORDS.items()
        }

        # Compile subcategory patterns
        self.injury_subcat_patterns = {
            subcat: [re.compile(p, re.IGNORECASE) for p in patterns]
            for subcat, patterns in INJURY_SUBCATEGORIES.items()
        }
        self.trade_subcat_patterns = {
            subcat: [re.compile(p, re.IGNORECASE) for p in patterns]
            for subcat, patterns in TRADE_SUBCATEGORIES.items()
        }

        # Player name pattern - captures names like "LeBron James", "A.J. Green"
        # Also handles names at start of sentences and after punctuation
        self.player_name_pattern = re.compile(
            r'(?:^|[.\s])([A-Z][a-zA-Z\']+(?:\s[A-Z]\.?)?\s+[A-Z][a-zA-Z\']+(?:\s+(?:Jr\.|Sr\.|II|III|IV))?)\b'
        )

        logger.info("Initialized KeywordExtractor")

    def extract(
        self,
        article_id: str,
        title: str,
        summary: str,
        sport: str = 'nba'
    ) -> ExtractionResult:
        """
        Extract information from an article.

        Args:
            article_id: Unique article identifier
            title: Article title
            summary: Article summary/description
            sport: 'nba' or 'mlb'

        Returns:
            ExtractionResult with category, players, teams, etc.
        """
        text = f"{title} {summary}"

        # Categorize the article
        category, confidence, keywords = self._categorize(text)

        # Get subcategory
        subcategory = self._get_subcategory(text, category)

        # Extract player mentions
        player_mentions = self._extract_players(text)

        # Extract team mentions
        teams = self._extract_teams(text, sport)

        return ExtractionResult(
            article_id=article_id,
            category=category,
            subcategory=subcategory,
            confidence=confidence,
            player_mentions=player_mentions,
            teams_mentioned=teams,
            keywords_matched=keywords,
        )

    def _categorize(self, text: str) -> Tuple[NewsCategory, float, List[str]]:
        """
        Determine the category of the article.

        Returns:
            (category, confidence, matched_keywords)
        """
        scores: Dict[NewsCategory, int] = {}
        matched: Dict[NewsCategory, List[str]] = {}

        for category, patterns in self.category_patterns.items():
            scores[category] = 0
            matched[category] = []

            for pattern in patterns:
                matches = pattern.findall(text)
                if matches:
                    scores[category] += len(matches)
                    matched[category].extend(matches)

        # Find best category
        if not any(scores.values()):
            return NewsCategory.OTHER, 0.5, []

        best_category = max(scores, key=scores.get)
        total_matches = sum(scores.values())
        confidence = min(0.95, 0.5 + (scores[best_category] / max(total_matches, 1)) * 0.5)

        return best_category, confidence, matched[best_category][:5]

    def _get_subcategory(self, text: str, category: NewsCategory) -> Optional[str]:
        """Get subcategory based on main category."""
        if category == NewsCategory.INJURY:
            patterns = self.injury_subcat_patterns
        elif category == NewsCategory.TRADE:
            patterns = self.trade_subcat_patterns
        else:
            return None

        for subcat, subcat_patterns in patterns.items():
            for pattern in subcat_patterns:
                if pattern.search(text):
                    return subcat

        return None

    def _extract_players(self, text: str) -> List[ExtractedMention]:
        """Extract player name mentions from text."""
        mentions = []
        seen_names: Set[str] = set()

        for match in self.player_name_pattern.finditer(text):
            name = match.group(1)

            # Skip common false positives
            if self._is_false_positive(name):
                continue

            # Skip duplicates
            name_lower = name.lower()
            if name_lower in seen_names:
                continue
            seen_names.add(name_lower)

            # Get surrounding context
            start = max(0, match.start() - 30)
            end = min(len(text), match.end() + 30)
            context = text[start:end].strip()

            mentions.append(ExtractedMention(
                name_as_written=name,
                likely_full_name=name,
                position_in_text=match.start(),
                context=context,
                confidence=0.8,  # Base confidence for regex match
            ))

        return mentions

    def _is_false_positive(self, name: str) -> bool:
        """Check if a name match is likely a false positive."""
        false_positives = {
            # Locations/Teams
            'The Associated', 'New York', 'Los Angeles', 'San Antonio',
            'San Francisco', 'San Diego', 'New Orleans', 'Oklahoma City',
            'Golden State', 'Tampa Bay', 'Kansas City', 'St Louis',
            'The Atlanta', 'The Boston', 'The Chicago', 'The Cleveland',
            'The Dallas', 'The Denver', 'The Detroit', 'The Houston',
            'The Indiana', 'The Lakers', 'The Miami', 'The Milwaukee',
            'The Phoenix', 'The Portland', 'The Sacramento', 'The Toronto',
            'The Washington', 'The Brooklyn', 'The Charlotte', 'The Memphis',
            'The Minnesota', 'The Orlando', 'The Utah',
            'Marlins Chicago', 'Cubs Chicago', 'Sox Chicago',
            # League terms
            'All Star', 'All Stars', 'Most Valuable', 'Player Of',
            'Eastern Conference', 'Western Conference',
            'National Basketball', 'Major League', 'National League',
            'American League',
            # Time references
            'Last Night', 'This Week', 'Next Season', 'Last Season',
            'First Half', 'Second Half', 'Third Quarter', 'Fourth Quarter',
            'Opening Day', 'Trade Deadline',
            # Common phrases
            'Breaking News', 'Sources Say', 'According To',
            'Head Coach', 'General Manager', 'Front Office',
        }
        # Check exact match
        if name in false_positives:
            return True
        # Check if starts with "The "
        if name.startswith('The '):
            return True
        # Check if contains team city names incorrectly
        if any(city in name for city in ['Marlins', 'Cubs', 'Sox', 'Dodgers', 'Yankees']):
            if len(name.split()) > 2:
                return True
        # Filter out common non-player patterns
        non_player_patterns = [
            r'^(NBA|MLB|NFL|NHL)\s',  # League prefixes
            r'^(ESPN|CBS|Fox|NBC|ABC)\s',  # Network prefixes
            r'^(Ole|Notre|Saint|San|Santa)\s',  # College/place prefixes
            r"^(SportsLine|DraftKings|FanDuel)",  # Company names
            r"^An?\s[A-Z]",  # "A/An + word" patterns
            r"'s\s",  # Possessive patterns like "Spurs' Sochan"
        ]
        for pattern in non_player_patterns:
            if re.search(pattern, name):
                return True
        return False

    def _extract_teams(self, text: str, sport: str) -> List[str]:
        """Extract team mentions from text."""
        teams_dict = NBA_TEAMS if sport == 'nba' else MLB_TEAMS
        found_teams: Set[str] = set()
        text_lower = text.lower()

        for abbr, names in teams_dict.items():
            for name in names:
                if name.lower() in text_lower:
                    found_teams.add(abbr)
                    break

        return list(found_teams)

    def extract_batch(
        self,
        articles: List[dict],
        sport: str = 'nba'
    ) -> List[ExtractionResult]:
        """
        Extract from multiple articles.

        Args:
            articles: List of article dicts with 'article_id', 'title', 'summary'
            sport: 'nba' or 'mlb'

        Returns:
            List of ExtractionResult objects
        """
        results = []
        for article in articles:
            result = self.extract(
                article_id=article['article_id'],
                title=article['title'],
                summary=article.get('summary', ''),
                sport=sport,
            )
            results.append(result)

        return results


def test_extractor():
    """Test the keyword extractor."""
    logging.basicConfig(level=logging.INFO)

    extractor = KeywordExtractor()

    # Test articles
    test_articles = [
        {
            'article_id': 'test1',
            'title': 'LeBron James ruled out vs. Spurs with ankle injury',
            'summary': 'Lakers star LeBron James will miss Wednesday\'s game against San Antonio due to a left ankle sprain.',
        },
        {
            'article_id': 'test2',
            'title': 'Hawks trade Trae Young to Wizards for CJ McCollum',
            'summary': 'The Atlanta Hawks have traded All-Star guard Trae Young to Washington in exchange for CJ McCollum.',
        },
        {
            'article_id': 'test3',
            'title': 'Anthony Davis questionable for Thursday game',
            'summary': 'Davis is dealing with knee soreness and is listed as questionable for the Lakers matchup.',
        },
        {
            'article_id': 'test4',
            'title': 'Cubs acquire Edward Cabrera from Marlins',
            'summary': 'Chicago Cubs have acquired pitcher Edward Cabrera from Miami in a trade.',
        },
    ]

    print("\n" + "="*60)
    print("  Keyword Extractor Test")
    print("="*60 + "\n")

    for article in test_articles:
        sport = 'mlb' if 'Cubs' in article['title'] or 'Marlins' in article['title'] else 'nba'
        result = extractor.extract(
            article['article_id'],
            article['title'],
            article['summary'],
            sport=sport
        )

        print(f"Title: {article['title']}")
        print(f"  Category: {result.category.value} ({result.confidence:.0%})")
        print(f"  Subcategory: {result.subcategory}")
        print(f"  Players: {[m.name_as_written for m in result.player_mentions]}")
        print(f"  Teams: {result.teams_mentioned}")
        print(f"  Keywords: {result.keywords_matched}")
        print()


if __name__ == '__main__':
    test_extractor()
