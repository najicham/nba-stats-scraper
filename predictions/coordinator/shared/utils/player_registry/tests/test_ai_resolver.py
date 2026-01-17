#!/usr/bin/env python3
"""
Unit tests for AINameResolver class.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
import json

from shared.utils.player_registry.ai_resolver import (
    AINameResolver,
    ResolutionContext,
    AIResolution
)


class TestResolutionContext(unittest.TestCase):
    """Test ResolutionContext dataclass."""

    def test_create_minimal(self):
        """Test creating context with minimal fields."""
        ctx = ResolutionContext(
            unresolved_lookup='marcusmorris',
            unresolved_display='Marcus Morris'
        )
        self.assertEqual(ctx.unresolved_lookup, 'marcusmorris')
        self.assertEqual(ctx.unresolved_display, 'Marcus Morris')
        self.assertIsNone(ctx.team_abbr)
        self.assertIsNone(ctx.season)
        self.assertEqual(ctx.team_roster, [])
        self.assertEqual(ctx.similar_names, [])
        self.assertEqual(ctx.source, 'unknown')

    def test_create_full(self):
        """Test creating context with all fields."""
        ctx = ResolutionContext(
            unresolved_lookup='marcusmorris',
            unresolved_display='Marcus Morris',
            team_abbr='LAC',
            season='2021-22',
            team_roster=['Marcus Morris Sr.', 'Paul George'],
            similar_names=['marcusmorrissr', 'marcusmorrisjr'],
            source='nba_gamebook'
        )
        self.assertEqual(ctx.team_abbr, 'LAC')
        self.assertEqual(ctx.season, '2021-22')
        self.assertEqual(len(ctx.team_roster), 2)
        self.assertEqual(len(ctx.similar_names), 2)
        self.assertEqual(ctx.source, 'nba_gamebook')


class TestAIResolution(unittest.TestCase):
    """Test AIResolution dataclass."""

    def test_create(self):
        """Test creating resolution result."""
        result = AIResolution(
            unresolved_lookup='marcusmorris',
            resolution_type='MATCH',
            canonical_lookup='marcusmorrissr',
            confidence=0.98,
            reasoning='Missing Sr. suffix',
            ai_model='claude-3-haiku-20240307',
            api_call_id='msg_123',
            input_tokens=500,
            output_tokens=50
        )
        self.assertEqual(result.resolution_type, 'MATCH')
        self.assertEqual(result.canonical_lookup, 'marcusmorrissr')
        self.assertEqual(result.confidence, 0.98)


class TestAINameResolverInit(unittest.TestCase):
    """Test AINameResolver initialization."""

    def test_init_with_provided_key(self):
        """Test initialization with provided API key."""
        with patch.dict('sys.modules', {'anthropic': MagicMock()}):
            resolver = AINameResolver(api_key='test-key')
            # If we got here without error, the key was used

    @patch('shared.utils.auth_utils.get_api_key')
    def test_init_fetches_key_if_not_provided(self, mock_get_key):
        """Test that key is fetched if not provided."""
        mock_get_key.return_value = 'fetched-key'

        with patch.dict('sys.modules', {'anthropic': MagicMock()}):
            resolver = AINameResolver()
            mock_get_key.assert_called_once()

    @patch('shared.utils.auth_utils.get_api_key')
    def test_init_raises_if_no_key(self, mock_get_key):
        """Test that ValueError is raised if no key available."""
        mock_get_key.return_value = None

        with self.assertRaises(ValueError) as ctx:
            AINameResolver()

        self.assertIn('API key not found', str(ctx.exception))


class TestAINameResolverPromptBuilding(unittest.TestCase):
    """Test prompt building methods."""

    def setUp(self):
        """Set up resolver with mocked client."""
        with patch.dict('sys.modules', {'anthropic': MagicMock()}):
            self.resolver = AINameResolver(api_key='test-key')

    def test_build_prompt_basic(self):
        """Test basic prompt building."""
        ctx = ResolutionContext(
            unresolved_lookup='marcusmorris',
            unresolved_display='Marcus Morris',
            team_abbr='LAC',
            season='2021-22'
        )

        prompt = self.resolver._build_prompt(ctx)

        self.assertIn('marcusmorris', prompt)
        self.assertIn('Marcus Morris', prompt)
        self.assertIn('LAC', prompt)
        self.assertIn('2021-22', prompt)
        self.assertIn('MATCH', prompt)
        self.assertIn('NEW_PLAYER', prompt)
        self.assertIn('DATA_ERROR', prompt)

    def test_format_roster_empty(self):
        """Test roster formatting when empty."""
        result = self.resolver._format_roster([])
        self.assertIn('roster not available', result)

    def test_format_roster_with_players(self):
        """Test roster formatting with players."""
        roster = ['LeBron James', 'Anthony Davis']
        result = self.resolver._format_roster(roster)

        self.assertIn('LeBron James', result)
        self.assertIn('Anthony Davis', result)

    def test_format_roster_truncates_large(self):
        """Test that large rosters are truncated."""
        roster = [f'Player {i}' for i in range(50)]
        result = self.resolver._format_roster(roster)

        self.assertIn('Player 0', result)
        self.assertIn('Player 29', result)
        self.assertIn('and 20 more', result)

    def test_format_candidates_empty(self):
        """Test candidates formatting when empty."""
        result = self.resolver._format_candidates([])
        self.assertIn('no similar names found', result)

    def test_format_candidates_truncates_large(self):
        """Test that large candidate lists are truncated."""
        candidates = [f'player{i}' for i in range(30)]
        result = self.resolver._format_candidates(candidates)

        self.assertIn('player0', result)
        self.assertIn('player19', result)
        self.assertIn('and 10 more', result)


class TestAINameResolverResponseParsing(unittest.TestCase):
    """Test response parsing methods."""

    def setUp(self):
        """Set up resolver with mocked client."""
        with patch.dict('sys.modules', {'anthropic': MagicMock()}):
            self.resolver = AINameResolver(api_key='test-key')

    def _make_mock_response(self, content: str):
        """Create mock Anthropic response."""
        mock_response = Mock()
        mock_response.content = [Mock(text=content)]
        mock_response.id = 'msg_test123'
        mock_response.usage = Mock(input_tokens=100, output_tokens=50)
        return mock_response

    def test_parse_match_response(self):
        """Test parsing MATCH response."""
        response_json = json.dumps({
            'resolution_type': 'MATCH',
            'canonical_lookup': 'marcusmorrissr',
            'confidence': 0.98,
            'reasoning': 'Missing Sr. suffix'
        })

        ctx = ResolutionContext(
            unresolved_lookup='marcusmorris',
            unresolved_display='Marcus Morris'
        )

        result = self.resolver._parse_response(
            self._make_mock_response(response_json),
            ctx
        )

        self.assertEqual(result.resolution_type, 'MATCH')
        self.assertEqual(result.canonical_lookup, 'marcusmorrissr')
        self.assertEqual(result.confidence, 0.98)
        self.assertEqual(result.reasoning, 'Missing Sr. suffix')

    def test_parse_new_player_response(self):
        """Test parsing NEW_PLAYER response."""
        response_json = json.dumps({
            'resolution_type': 'NEW_PLAYER',
            'canonical_lookup': None,
            'confidence': 0.85,
            'reasoning': 'Rookie not in registry'
        })

        ctx = ResolutionContext(
            unresolved_lookup='bronnyjames',
            unresolved_display='Bronny James'
        )

        result = self.resolver._parse_response(
            self._make_mock_response(response_json),
            ctx
        )

        self.assertEqual(result.resolution_type, 'NEW_PLAYER')
        self.assertIsNone(result.canonical_lookup)

    def test_parse_data_error_response(self):
        """Test parsing DATA_ERROR response."""
        response_json = json.dumps({
            'resolution_type': 'DATA_ERROR',
            'canonical_lookup': None,
            'confidence': 0.99,
            'reasoning': 'Retired player'
        })

        ctx = ResolutionContext(
            unresolved_lookup='michaeljordan',
            unresolved_display='Michael Jordan'
        )

        result = self.resolver._parse_response(
            self._make_mock_response(response_json),
            ctx
        )

        self.assertEqual(result.resolution_type, 'DATA_ERROR')

    def test_parse_markdown_wrapped_json(self):
        """Test parsing JSON wrapped in markdown code fence."""
        response_text = '''```json
{
    "resolution_type": "MATCH",
    "canonical_lookup": "marcusmorrissr",
    "confidence": 0.98,
    "reasoning": "Test"
}
```'''

        ctx = ResolutionContext(
            unresolved_lookup='marcusmorris',
            unresolved_display='Marcus Morris'
        )

        result = self.resolver._parse_response(
            self._make_mock_response(response_text),
            ctx
        )

        self.assertEqual(result.resolution_type, 'MATCH')
        self.assertEqual(result.canonical_lookup, 'marcusmorrissr')

    def test_parse_invalid_resolution_type_defaults_to_error(self):
        """Test that invalid resolution_type defaults to DATA_ERROR."""
        response_json = json.dumps({
            'resolution_type': 'INVALID',
            'canonical_lookup': None,
            'confidence': 0.8,
            'reasoning': 'Test'
        })

        ctx = ResolutionContext(
            unresolved_lookup='test',
            unresolved_display='Test'
        )

        result = self.resolver._parse_response(
            self._make_mock_response(response_json),
            ctx
        )

        self.assertEqual(result.resolution_type, 'DATA_ERROR')

    def test_parse_confidence_clamping(self):
        """Test that confidence is clamped to valid range."""
        response_json = json.dumps({
            'resolution_type': 'MATCH',
            'canonical_lookup': 'test',
            'confidence': 0.5,  # Below 0.7 minimum
            'reasoning': 'Test'
        })

        ctx = ResolutionContext(
            unresolved_lookup='test',
            unresolved_display='Test'
        )

        result = self.resolver._parse_response(
            self._make_mock_response(response_json),
            ctx
        )

        self.assertEqual(result.confidence, 0.7)

    def test_parse_match_without_canonical_becomes_error(self):
        """Test that MATCH without canonical_lookup becomes DATA_ERROR."""
        response_json = json.dumps({
            'resolution_type': 'MATCH',
            'canonical_lookup': None,  # Missing for MATCH
            'confidence': 0.9,
            'reasoning': 'Test'
        })

        ctx = ResolutionContext(
            unresolved_lookup='test',
            unresolved_display='Test'
        )

        result = self.resolver._parse_response(
            self._make_mock_response(response_json),
            ctx
        )

        self.assertEqual(result.resolution_type, 'DATA_ERROR')

    def test_parse_invalid_json_returns_error(self):
        """Test that invalid JSON returns DATA_ERROR."""
        ctx = ResolutionContext(
            unresolved_lookup='test',
            unresolved_display='Test'
        )

        result = self.resolver._parse_response(
            self._make_mock_response('not valid json'),
            ctx
        )

        self.assertEqual(result.resolution_type, 'DATA_ERROR')
        self.assertIn('JSON parse error', result.reasoning)


class TestAINameResolverResolution(unittest.TestCase):
    """Test resolution methods."""

    def setUp(self):
        """Set up resolver with mocked client."""
        self.mock_anthropic = MagicMock()
        with patch.dict('sys.modules', {'anthropic': self.mock_anthropic}):
            self.resolver = AINameResolver(api_key='test-key')

    def test_resolve_single_success(self):
        """Test successful single resolution."""
        mock_response = Mock()
        mock_response.content = [Mock(text=json.dumps({
            'resolution_type': 'MATCH',
            'canonical_lookup': 'marcusmorrissr',
            'confidence': 0.98,
            'reasoning': 'Missing Sr. suffix'
        }))]
        mock_response.id = 'msg_123'
        mock_response.usage = Mock(input_tokens=100, output_tokens=50)

        self.resolver.client.messages.create.return_value = mock_response

        ctx = ResolutionContext(
            unresolved_lookup='marcusmorris',
            unresolved_display='Marcus Morris',
            team_abbr='LAC',
            season='2021-22'
        )

        result = self.resolver.resolve_single(ctx)

        self.assertEqual(result.resolution_type, 'MATCH')
        self.assertEqual(result.canonical_lookup, 'marcusmorrissr')
        self.resolver.client.messages.create.assert_called_once()

    def test_resolve_single_api_error_returns_data_error(self):
        """Test that API errors return DATA_ERROR rather than raising."""
        self.resolver.client.messages.create.side_effect = Exception('API Error')

        ctx = ResolutionContext(
            unresolved_lookup='test',
            unresolved_display='Test'
        )

        result = self.resolver.resolve_single(ctx)

        self.assertEqual(result.resolution_type, 'DATA_ERROR')
        self.assertIn('AI call failed', result.reasoning)

    def test_resolve_batch(self):
        """Test batch resolution."""
        mock_response = Mock()
        mock_response.content = [Mock(text=json.dumps({
            'resolution_type': 'MATCH',
            'canonical_lookup': 'test',
            'confidence': 0.9,
            'reasoning': 'Test'
        }))]
        mock_response.id = 'msg_123'
        mock_response.usage = Mock(input_tokens=100, output_tokens=50)

        self.resolver.client.messages.create.return_value = mock_response

        contexts = [
            ResolutionContext(unresolved_lookup='player1', unresolved_display='Player 1'),
            ResolutionContext(unresolved_lookup='player2', unresolved_display='Player 2'),
        ]

        results = self.resolver.resolve_batch(contexts)

        self.assertEqual(len(results), 2)
        self.assertEqual(self.resolver.client.messages.create.call_count, 2)


if __name__ == '__main__':
    unittest.main()
