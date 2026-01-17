#!/usr/bin/env python3
"""
AI-powered name resolution using Claude API.

This module provides AI-based resolution for unresolved player names that
can't be matched through direct registry lookup or aliases.
"""

import os
import json
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class ResolutionContext:
    """Context provided to AI for resolution."""
    unresolved_lookup: str
    unresolved_display: str
    team_abbr: Optional[str] = None
    season: Optional[str] = None
    team_roster: List[str] = field(default_factory=list)
    similar_names: List[str] = field(default_factory=list)
    source: str = "unknown"


@dataclass
class AIResolution:
    """Result from AI resolution."""
    unresolved_lookup: str
    resolution_type: str  # 'MATCH', 'NEW_PLAYER', 'DATA_ERROR'
    canonical_lookup: Optional[str]
    confidence: float
    reasoning: str
    ai_model: str
    api_call_id: str
    input_tokens: int
    output_tokens: int


class AINameResolver:
    """
    Resolve player names using Claude AI.

    Always makes a decision - never returns "unknown" or "needs review".

    Example:
        resolver = AINameResolver()
        context = ResolutionContext(
            unresolved_lookup='marcusmorris',
            unresolved_display='Marcus Morris',
            team_abbr='LAC',
            season='2021-22',
            team_roster=['Marcus Morris Sr.', 'Paul George', ...],
            similar_names=['marcusmorrissr', 'marcusmorrisjr']
        )
        result = resolver.resolve_single(context)
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """
        Initialize AI resolver.

        Args:
            api_key: Anthropic API key. If not provided, will try:
                     1. ANTHROPIC_API_KEY environment variable (local dev)
                     2. Secret Manager 'anthropic-api-key' (Cloud Run)
            model: Model to use (defaults to claude-3-haiku-20240307)
        """
        # Get API key from parameter, env var, or Secret Manager
        if api_key is None:
            from shared.utils.auth_utils import get_api_key
            api_key = get_api_key(
                secret_name='anthropic-api-key',
                default_env_var='ANTHROPIC_API_KEY'
            )
            if not api_key:
                raise ValueError(
                    "Anthropic API key not found. Set ANTHROPIC_API_KEY env var "
                    "or create 'anthropic-api-key' secret in Secret Manager."
                )

        try:
            import anthropic
            self.client = anthropic.Anthropic(api_key=api_key)
        except ImportError:
            raise ImportError("anthropic package not installed. Run: pip install anthropic")

        self.model = model or os.environ.get('AI_RESOLUTION_MODEL', 'claude-3-haiku-20240307')
        self.high_confidence_threshold = float(os.environ.get('AI_HIGH_CONFIDENCE_THRESHOLD', '0.9'))
        self.low_confidence_threshold = float(os.environ.get('AI_LOW_CONFIDENCE_THRESHOLD', '0.7'))

        logger.info(f"Initialized AINameResolver with model={self.model}")

    def resolve_single(self, context: ResolutionContext) -> AIResolution:
        """
        Resolve a single unresolved player name.

        Args:
            context: ResolutionContext with name and surrounding information

        Returns:
            AIResolution with decision, confidence, and reasoning
        """
        prompt = self._build_prompt(context)

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )

            result = self._parse_response(response, context)
            logger.info(
                f"AI resolved '{context.unresolved_lookup}': "
                f"{result.resolution_type} -> {result.canonical_lookup} "
                f"(confidence: {result.confidence:.2f})"
            )
            return result

        except Exception as e:
            logger.error(f"AI resolution failed for {context.unresolved_lookup}: {e}")
            # Return low-confidence error rather than failing
            return AIResolution(
                unresolved_lookup=context.unresolved_lookup,
                resolution_type='DATA_ERROR',
                canonical_lookup=None,
                confidence=0.5,
                reasoning=f"AI call failed: {str(e)[:100]}",
                ai_model=self.model,
                api_call_id='error',
                input_tokens=0,
                output_tokens=0
            )

    def resolve_batch(self, contexts: List[ResolutionContext],
                     max_batch_size: int = 10) -> List[AIResolution]:
        """
        Resolve multiple names efficiently.

        Args:
            contexts: List of ResolutionContext objects
            max_batch_size: Maximum names per batch (for rate limiting)

        Returns:
            List of AIResolution objects
        """
        results = []

        for i, context in enumerate(contexts):
            logger.info(f"Resolving {i+1}/{len(contexts)}: {context.unresolved_lookup}")
            result = self.resolve_single(context)
            results.append(result)

        return results

    def _build_prompt(self, context: ResolutionContext) -> str:
        """Build the AI prompt with full context."""

        roster_str = self._format_roster(context.team_roster)
        candidates_str = self._format_candidates(context.similar_names)

        return f"""You are an NBA player name resolution expert. Your job is to ALWAYS make a decision - never say "I don't know" or "needs manual review."

Given an unresolved player name, you must return ONE of:
1. MATCH - the canonical player this name refers to
2. NEW_PLAYER - this appears to be a player not in our registry yet
3. DATA_ERROR - this name is implausible/wrong

Context:
- Unresolved name: "{context.unresolved_display}" (normalized: "{context.unresolved_lookup}")
- Team: {context.team_abbr or "unknown"}
- Season: {context.season or "unknown"}
- Source: {context.source}

Team roster that season ({len(context.team_roster)} players):
{roster_str}

Similar names in registry ({len(context.similar_names)} candidates):
{candidates_str}

Analysis steps:
1. Check if name is a close match to roster players (suffix differences like Jr/Sr/II/III, nicknames, encoding issues)
2. If no roster match, check similar_names for potential matches
3. If no match found, check if name is plausible for a real NBA player
4. If implausible (e.g., "Michael Jordan" in 2024), mark as DATA_ERROR

Return ONLY valid JSON (no markdown, no preamble):
{{
  "resolution_type": "MATCH" | "NEW_PLAYER" | "DATA_ERROR",
  "canonical_lookup": "player_lookup_value" or null,
  "confidence": 0.7-1.0,
  "reasoning": "Brief explanation (max 100 chars)"
}}

Examples:
- "marcusmorris" on LAC, similar names has "marcusmorrissr" -> {{"resolution_type": "MATCH", "canonical_lookup": "marcusmorrissr", "confidence": 0.98, "reasoning": "Missing Sr. suffix, same team/season"}}
- "bronnyjames" on LAL in 2024-25, not in registry -> {{"resolution_type": "NEW_PLAYER", "canonical_lookup": null, "confidence": 0.85, "reasoning": "Rookie debut, not in registry yet"}}
- "michaeljordan" on LAL in 2024 -> {{"resolution_type": "DATA_ERROR", "canonical_lookup": null, "confidence": 0.99, "reasoning": "Jordan retired in 2003, implausible"}}

CRITICAL: You must always provide a resolution_type. Never respond with "uncertain" or "needs review."
Confidence must be between 0.7 and 1.0. If less confident than 0.7, choose DATA_ERROR."""

    def _format_roster(self, roster: List[str]) -> str:
        """Format roster for prompt."""
        if not roster:
            return "  (roster not available)"
        # Limit to 30 players to keep prompt size manageable
        limited = roster[:30]
        result = "\n".join(f"  - {name}" for name in limited)
        if len(roster) > 30:
            result += f"\n  ... and {len(roster) - 30} more"
        return result

    def _format_candidates(self, candidates: List[str]) -> str:
        """Format similar candidates for prompt."""
        if not candidates:
            return "  (no similar names found)"
        # Limit to 20 candidates
        limited = candidates[:20]
        result = "\n".join(f"  - {name}" for name in limited)
        if len(candidates) > 20:
            result += f"\n  ... and {len(candidates) - 20} more"
        return result

    def _parse_response(self, response, context: ResolutionContext) -> AIResolution:
        """Parse Claude's response into AIResolution."""

        try:
            # Extract JSON from response
            content = response.content[0].text.strip()

            # Remove markdown code fences if present
            if '```json' in content:
                content = content.split('```json')[1].split('```')[0]
            elif '```' in content:
                content = content.split('```')[1].split('```')[0]

            content = content.strip()
            data = json.loads(content)

            # Validate resolution_type
            resolution_type = data.get('resolution_type')
            if resolution_type not in ['MATCH', 'NEW_PLAYER', 'DATA_ERROR']:
                logger.warning(f"Invalid resolution_type: {resolution_type}, defaulting to DATA_ERROR")
                resolution_type = 'DATA_ERROR'

            # Validate confidence
            confidence = float(data.get('confidence', 0.7))
            if not (0.7 <= confidence <= 1.0):
                logger.warning(f"Confidence {confidence} outside expected range, clamping")
                confidence = max(0.7, min(1.0, confidence))

            # Validate canonical_lookup for MATCH type
            canonical_lookup = data.get('canonical_lookup')
            if resolution_type == 'MATCH' and not canonical_lookup:
                logger.warning("MATCH type but no canonical_lookup, switching to DATA_ERROR")
                resolution_type = 'DATA_ERROR'
                canonical_lookup = None

            return AIResolution(
                unresolved_lookup=context.unresolved_lookup,
                resolution_type=resolution_type,
                canonical_lookup=canonical_lookup,
                confidence=confidence,
                reasoning=data.get('reasoning', 'No reasoning provided')[:200],
                ai_model=self.model,
                api_call_id=response.id,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e}")
            logger.error(f"Response content: {response.content[0].text[:500]}")

            return AIResolution(
                unresolved_lookup=context.unresolved_lookup,
                resolution_type='DATA_ERROR',
                canonical_lookup=None,
                confidence=0.5,
                reasoning=f"JSON parse error: {str(e)[:50]}",
                ai_model=self.model,
                api_call_id=response.id if hasattr(response, 'id') else 'parse_error',
                input_tokens=response.usage.input_tokens if hasattr(response, 'usage') else 0,
                output_tokens=response.usage.output_tokens if hasattr(response, 'usage') else 0
            )
        except Exception as e:
            logger.error(f"Unexpected error parsing response: {e}")

            return AIResolution(
                unresolved_lookup=context.unresolved_lookup,
                resolution_type='DATA_ERROR',
                canonical_lookup=None,
                confidence=0.5,
                reasoning=f"Parse error: {str(e)[:50]}",
                ai_model=self.model,
                api_call_id='error',
                input_tokens=0,
                output_tokens=0
            )
