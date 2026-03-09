"""
Claude API Pick Reviewer — Post-pipeline enrichment layer.

Reviews best bet picks using Claude for situational context that statistical
features can't capture: trades, motivation, playoff implications, revenge games,
coaching decisions, narrative context.

Architecture:
- Runs AFTER Phase 6 export (async, fail-open)
- Logs all reviews to BigQuery `claude_pick_reviews` table
- Pure observation for first 30+ days — no picks blocked or modified
- Batches all picks into ONE API call for cross-pick analysis

Usage:
    reviewer = ClaudePickReviewer()
    reviews = reviewer.review_picks(picks, slate_context)
    reviewer.write_reviews_to_bq(reviews, game_date)
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ── Cost constants (Sonnet 4.6) ──────────────────────────────────────────────
SONNET_INPUT_COST_PER_1M = 3.00
SONNET_OUTPUT_COST_PER_1M = 15.00
HAIKU_INPUT_COST_PER_1M = 1.00
HAIKU_OUTPUT_COST_PER_1M = 5.00

# ── Prompt version (bump when prompt changes) ────────────────────────────────
PROMPT_VERSION = "v2_adversarial"

# ── Default model ─────────────────────────────────────────────────────────────
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# ── Closed vocabulary for risk flags ──────────────────────────────────────────
RISK_FLAGS = [
    "b2b_fatigue",            # Second night of back-to-back
    "blowout_risk",           # Large spread → starters sit early, garbage time
    "injury_return",          # Player returning from injury, minutes uncertain
    "minutes_uncertainty",    # Recent minutes fluctuating significantly
    "hot_streak_regression",  # Scoring well above season average recently
    "cold_streak_continuation",  # Scoring poorly, trend may continue
    "revenge_game",           # Playing former team (emotional, unpredictable)
    "rest_disadvantage",      # Opponent more rested
    "playoff_seeding",        # Team clinching/eliminated, effort may vary
    "role_change",            # Player's role recently shifted (trade, lineup change)
    "matchup_concern",        # Tough individual matchup or pace mismatch
    "line_movement_suspicious",  # Line moved significantly or suspiciously
    "trend_direction_conflict",  # Pick direction conflicts with player's recent scoring trend
    "low_volume_variance",    # Bench/role player with high scoring variance
    "season_context",         # End of season, tanking, resting starters
]

SUPPORTING_FACTORS = [
    "favorable_matchup",      # Weak defender or pace advantage
    "pace_advantage",         # High-pace game environment
    "usage_increase",         # More touches expected (teammate out)
    "consistent_performer",   # Low scoring variance, reliable output
    "home_court",             # Home team advantage
    "rest_advantage",         # Player more rested than opponent
    "teammate_out_boost",     # Key teammate absent, more usage expected
    "hot_shooting",           # Recent shooting above career norms
    "minutes_stability",      # Stable, high minutes recently
    "strong_recent_form",     # Playing well in recent games
    "line_value",             # Line appears mispriced based on context
    "historical_vs_opponent", # Good career numbers vs this opponent
    "team_motivation",        # Playoff race, rivalry, statement game
    "scoring_floor",          # Player's worst recent game was still near/above the line
]


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class PickContext:
    """Basketball-legible context for a single pick. No model internals."""
    # Core
    player_name: str
    team: str
    opponent: str
    is_home: bool
    game_time: str
    line_value: float
    predicted_points: float
    edge: float
    direction: str  # OVER or UNDER

    # Player recent stats
    last_3_games_pts: list[float] = field(default_factory=list)
    season_ppg: Optional[float] = None
    season_minutes: Optional[float] = None
    season_usage: Optional[float] = None
    season_fg_pct: Optional[float] = None
    season_ft_rate: Optional[float] = None
    scoring_trend: Optional[str] = None  # "trending up", "trending down", "stable"
    points_variance: Optional[float] = None  # std dev

    # Line movement
    prev_line: Optional[float] = None
    line_change_pct: Optional[float] = None
    multi_book_std: Optional[float] = None  # bookmaker disagreement

    # Game context
    game_spread: Optional[float] = None
    implied_team_total: Optional[float] = None
    is_b2b: Optional[bool] = None

    # Injury/roster
    star_teammates_out: int = 0
    opponent_stars_out: int = 0
    player_injury_status: Optional[str] = None

    # Signals (plain English only)
    signal_descriptions: list[str] = field(default_factory=list)

    # Streaks
    over_under_last_5: Optional[str] = None  # e.g. "OOUOU"
    prediction_results_last_5: Optional[str] = None  # e.g. "WLWWL"

    # Pick metadata
    player_tier: Optional[str] = None  # bench/role/starter/star
    is_rescued: bool = False
    is_ultra: bool = False
    rank: Optional[int] = None

    # Matchup history
    career_avg_vs_opponent: Optional[float] = None
    career_games_vs_opponent: Optional[int] = None


@dataclass
class SlateContext:
    """Cross-pick context for the full slate."""
    game_date: str
    total_games_today: int = 0
    total_picks: int = 0
    over_count: int = 0
    under_count: int = 0
    calendar_regime: str = "normal"  # normal, toxic_window, post_asb
    bb_hr_7d: Optional[float] = None
    picks_from_same_game: dict = field(default_factory=dict)  # game_id -> count


@dataclass
class VulnerablePick:
    """A pick Claude flagged as vulnerable (top 3 most likely to lose)."""
    pick_number: int
    risk_flags: list[str]
    reasoning: str


@dataclass
class OtherPick:
    """Claude's brief assessment of a non-vulnerable pick."""
    pick_number: int
    assessment: str  # "clean", "minor_concern", "looks_strong"
    note: str


@dataclass
class SlateReview:
    """Claude's adversarial review of the full slate."""
    vulnerable_picks: list[VulnerablePick]  # Exactly 3, ranked
    other_picks: list[OtherPick]
    slate_observations: list[str]
    model_used: str = ""
    prompt_version: str = PROMPT_VERSION
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0


# ── Prompt builder ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = f"""You are a skeptical NBA analyst stress-testing player prop picks. Your job is to find the **weakest picks** on this slate — the ones most likely to lose.

## Your Role
A statistical model selected these picks. Your job is NOT to validate its reasoning. Instead, you are looking for **situational red flags** the model cannot capture: narrative context, schedule factors, role changes, blowout dynamics, and common-sense contradictions.

You are shown each player's stats and the betting line. Form your OWN opinion about whether the pick direction makes sense, independent of the model.

## CRITICAL: Do NOT Echo the Model
You are NOT given the model's reasoning or signals. You see only player stats and game context. Your value comes from INDEPENDENT assessment. If you have no strong opinion, say so honestly — that is more useful than a lukewarm agreement.

## Your Task
1. **Identify the 3 most vulnerable picks** on this slate. Rank them from most vulnerable (#1 = most likely to lose) to least vulnerable (#3).
2. For each of the remaining picks, give a brief assessment.
3. Note any **slate-level concerns** (concentration in one game, heavy directional lean, correlated exposure).

## Response Format
Return a JSON object with this exact structure:

```json
{{
  "vulnerable_picks": [
    {{
      "pick_number": 3,
      "risk_flags": ["trend_direction_conflict"],
      "reasoning": "1-2 sentence explanation of the specific vulnerability"
    }},
    {{
      "pick_number": 7,
      "risk_flags": ["blowout_risk"],
      "reasoning": "1-2 sentence explanation"
    }},
    {{
      "pick_number": 12,
      "risk_flags": ["low_volume_variance"],
      "reasoning": "1-2 sentence explanation"
    }}
  ],
  "other_picks": [
    {{
      "pick_number": 1,
      "assessment": "clean",
      "note": "Optional 1-sentence note if relevant, otherwise empty string"
    }}
  ],
  "slate_observations": [
    "Any cross-pick structural concerns"
  ]
}}
```

## Assessment values for other_picks
- **"clean"**: No situational red flags. No strong opinion either way.
- **"minor_concern"**: Small risk factor, but not enough to flag as vulnerable.
- **"looks_strong"**: Situational factors actively support this pick.

## Allowed Risk Flags (use ONLY these exact strings)
{json.dumps(RISK_FLAGS, indent=2)}

## Important Rules
1. Today's date is {{game_date}}. Do NOT reference events after this date.
2. Do NOT speculate about injuries, trades, or news you haven't been explicitly told about.
3. You MUST pick exactly 3 vulnerable picks — even if the slate looks strong, identify the 3 weakest.
4. Focus on what the STATS TELL YOU: Does the pick direction make sense given recent scoring? Does the line seem reasonable given the player's average? Are there game-script concerns from the spread?
5. Keep all reasoning to 1-2 sentences max.
6. Return ONLY valid JSON — no markdown, no commentary outside the JSON structure.
"""


def build_pick_prompt(pick: PickContext, pick_number: int) -> str:
    """Format a single pick into a human-readable prompt section.

    v2: No model prediction, no edge, no signals. Pure basketball context
    so Claude forms an independent opinion.
    """
    lines = []

    # Header with number for reliable matching
    home_away = "HOME" if pick.is_home else "AWAY"
    lines.append(f"### Pick #{pick_number}: {pick.player_name} ({pick.team} {home_away} vs {pick.opponent})")
    lines.append(f"**{pick.direction} {pick.line_value} pts**")

    # Player stats — let Claude form its own view
    if pick.last_3_games_pts:
        pts_str = ", ".join(f"{p:.0f}" for p in pick.last_3_games_pts)
        lines.append(f"Last 3 games: {pts_str} pts")

    stats = []
    if pick.season_ppg is not None:
        stats.append(f"Season avg: {pick.season_ppg:.1f} PPG")
    if pick.season_minutes is not None:
        stats.append(f"{pick.season_minutes:.0f} MPG")
    if stats:
        lines.append(" | ".join(stats))

    if pick.points_variance is not None:
        lines.append(f"Scoring std dev: {pick.points_variance:.1f} pts")
    if pick.scoring_trend:
        lines.append(f"Trend: {pick.scoring_trend}")

    # Line movement — critical for anomaly detection
    if pick.prev_line is not None:
        change = pick.line_value - pick.prev_line
        pct = abs(change / pick.prev_line * 100) if pick.prev_line else 0
        direction = "up" if change > 0 else "down"
        lines.append(f"Line: {pick.prev_line:.1f} → {pick.line_value} ({direction} {abs(change):.1f} pts, {pct:.0f}%)")

    # Game context
    game_info = []
    if pick.game_spread is not None:
        fav = pick.team if pick.game_spread < 0 else pick.opponent
        game_info.append(f"Spread: {fav} -{abs(pick.game_spread):.1f}")
    if pick.implied_team_total is not None:
        game_info.append(f"Implied total: {pick.implied_team_total:.1f}")
    if pick.is_b2b:
        game_info.append("**B2B**")
    if game_info:
        lines.append(" | ".join(game_info))

    # Injuries
    if pick.star_teammates_out > 0:
        lines.append(f"Star teammates out: {pick.star_teammates_out}")
    if pick.opponent_stars_out > 0:
        lines.append(f"Opponent stars out: {pick.opponent_stars_out}")

    # Streaks
    if pick.over_under_last_5:
        lines.append(f"O/U last 5: {pick.over_under_last_5}")

    return "\n".join(lines)


def build_slate_prompt(picks: list[PickContext], slate: SlateContext) -> str:
    """Build the full user prompt for all picks."""
    sections = []

    # Slate header
    sections.append(f"## Slate: {slate.game_date}")
    sections.append(f"Games: {slate.total_games_today} | Picks: {slate.total_picks} ({slate.over_count} OVER, {slate.under_count} UNDER)")
    if slate.calendar_regime != "normal":
        sections.append(f"Calendar: {slate.calendar_regime}")

    sections.append("")

    # Individual picks (numbered)
    for i, pick in enumerate(picks):
        sections.append(build_pick_prompt(pick, pick_number=i + 1))
        sections.append("")

    sections.append("---")
    sections.append("Identify the 3 most vulnerable picks and assess the rest.")

    return "\n".join(sections)


# ── Signal tag to plain English mapping ───────────────────────────────────────

SIGNAL_DESCRIPTIONS = {
    # Active signals
    "high_edge": "High statistical edge between model prediction and line",
    "model_health": "Source model is performing well recently",
    "edge_spread_optimal": "Edge and spread combination in optimal range",
    "home_under": "Home UNDER — historically 64% hit rate",
    "starter_under": "Starter-tier UNDER — most predictable range",
    "blowout_risk_under": "Potential blowout may limit minutes",
    "blowout_recovery": "Player bouncing back from blowout loss",
    "fast_pace_over": "Fast opponent pace creates more scoring opportunities",
    "volatile_scoring_over": "High scoring variance — upside favors OVER",
    "line_rising_over": "Line rose from previous game — market and model agree",
    "book_disagreement": "Sportsbooks disagree on this line",
    "self_creation_over": "Player creates own shots at high rate",
    "high_scoring_environment_over": "High implied total game environment",
    "3pt_bounce": "3-point shooting bounce-back expected",
    "low_line_over": "Low prop line — conservative lines easier to clear",
    "sharp_book_lean_over": "Sharp sportsbooks lean OVER on this player",
    "sharp_book_lean_under": "Sharp sportsbooks lean UNDER on this player",
    "sharp_line_drop_under": "Sharp line movement downward signals UNDER",
    "combo_3way": "Three strong signals combine — historically 95%+ hit rate",
    "combo_he_ms": "High edge + minutes surge combo — 95% hit rate",
    "projection_consensus_over": "Multiple projection sources agree OVER",
    "projection_consensus_under": "Multiple projection sources agree UNDER",
    "rest_advantage_2d": "2+ day rest advantage over opponent",
    "over_streak_reversion_under": "Player has gone OVER 4+ of last 5 — reversion expected",
    "volatile_starter_under": "High-variance starter — UNDER has edge",
    "downtrend_under": "Player on scoring downtrend — UNDER favored",
    "hot_form_over": "Player in strong recent form — OVER signal",
    "over_trend_over": "Player trending OVER recently",
    "scoring_momentum_over": "Scoring momentum building",
    "usage_surge_over": "Usage rate spiking recently",
    "bounce_back_over": "Bounce-back expected after poor game",
    "mean_reversion_under": "Scoring mean reversion expected",
    "prediction_sanity": "Model prediction flagged as potentially overconfident",
    "prop_line_drop_over": "Prop line dropped — may be mispriced low",
    "q4_scorer_over": "Player scores disproportionately in Q4",
    # Shadow / less common
    "predicted_pace_over": "Game pace predicted to be high",
    "dvp_favorable_over": "Opponent weak vs this position",
    "sharp_money_over": "Sharp money flowing toward OVER",
    "projection_disagreement": "Projection sources disagree with the line",
    "consistent_scorer_over": "Consistently hits scoring numbers",
    "career_matchup_over": "Historical success vs this opponent",
}


def translate_signals(signal_tags: list[str]) -> list[str]:
    """Convert signal tag codes to plain English descriptions."""
    # Skip base/meta signals that don't add context for Claude
    SKIP_SIGNALS = {"model_health", "edge_spread_optimal"}
    descriptions = []
    for tag in signal_tags:
        if tag in SKIP_SIGNALS:
            continue
        desc = SIGNAL_DESCRIPTIONS.get(tag, tag.replace("_", " ").title())
        descriptions.append(desc)
    return descriptions


# ── API caller ────────────────────────────────────────────────────────────────

class ClaudePickReviewer:
    """Reviews best bet picks using Claude API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
    ):
        self.model = model

        # Auth chain: param → env → Secret Manager
        if api_key is None:
            api_key = os.environ.get('ANTHROPIC_API_KEY')

        if api_key is None:
            try:
                from shared.utils.auth_utils import get_api_key
                api_key = get_api_key(
                    secret_name='anthropic-api-key',
                    default_env_var='ANTHROPIC_API_KEY'
                )
            except Exception as e:
                logger.debug(f"Secret Manager lookup failed: {e}")

        if not api_key:
            raise ValueError(
                "Anthropic API key not found. Set ANTHROPIC_API_KEY env var "
                "or create 'anthropic-api-key' secret in Secret Manager."
            )

        try:
            import anthropic
            self.client = anthropic.Anthropic(api_key=api_key)
        except ImportError:
            raise ImportError("anthropic package required: pip install anthropic")

        # Tracking
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost = 0.0

    def review_picks(
        self,
        picks: list[PickContext],
        slate: SlateContext,
    ) -> SlateReview:
        """Review all picks in a single API call."""
        # Build prompts
        system = SYSTEM_PROMPT.replace("{game_date}", slate.game_date)
        user_prompt = build_slate_prompt(picks, slate)

        logger.info(
            f"Reviewing {len(picks)} picks for {slate.game_date} "
            f"using {self.model} (prompt_version={PROMPT_VERSION})"
        )

        start_ms = int(time.time() * 1000)

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except Exception as e:
            logger.error(f"Claude API call failed: {e}", exc_info=True)
            # Fail-open: return empty review
            return SlateReview(
                pick_reviews=[],
                slate_observations=[f"API call failed: {str(e)}"],
                model_used=self.model,
                prompt_version=PROMPT_VERSION,
            )

        latency_ms = int(time.time() * 1000) - start_ms
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens

        # Cost calculation
        if "haiku" in self.model:
            cost = (
                (input_tokens / 1_000_000) * HAIKU_INPUT_COST_PER_1M
                + (output_tokens / 1_000_000) * HAIKU_OUTPUT_COST_PER_1M
            )
        else:
            cost = (
                (input_tokens / 1_000_000) * SONNET_INPUT_COST_PER_1M
                + (output_tokens / 1_000_000) * SONNET_OUTPUT_COST_PER_1M
            )

        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost += cost

        logger.info(
            f"Review complete: {input_tokens} in / {output_tokens} out, "
            f"${cost:.4f}, {latency_ms}ms"
        )

        # Parse response
        raw_text = response.content[0].text
        review = self._parse_response(raw_text, picks)
        review.model_used = self.model
        review.prompt_version = PROMPT_VERSION
        review.input_tokens = input_tokens
        review.output_tokens = output_tokens
        review.cost_usd = cost
        review.latency_ms = latency_ms

        return review

    def _parse_response(self, raw_text: str, picks: list[PickContext]) -> SlateReview:
        """Parse Claude's v2 adversarial JSON response."""
        # Strip markdown code fences if present
        text = raw_text.strip()
        if text.startswith("```"):
            first_newline = text.index("\n")
            text = text[first_newline + 1:]
        if text.endswith("```"):
            text = text[:-3].strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response as JSON: {e}")
            logger.debug(f"Raw response: {raw_text[:500]}")
            return SlateReview(
                vulnerable_picks=[],
                other_picks=[],
                slate_observations=[f"JSON parse error: {str(e)}"],
            )

        # Parse vulnerable picks
        vulnerable = []
        for vp in data.get("vulnerable_picks", []):
            risk_flags = [f for f in vp.get("risk_flags", []) if f in RISK_FLAGS]
            unknown = [f for f in vp.get("risk_flags", []) if f not in RISK_FLAGS]
            if unknown:
                logger.warning(f"Unknown risk flags from Claude: {unknown}")

            vulnerable.append(VulnerablePick(
                pick_number=vp.get("pick_number", 0),
                risk_flags=risk_flags,
                reasoning=vp.get("reasoning", ""),
            ))

        # Parse other picks
        others = []
        for op in data.get("other_picks", []):
            assessment = op.get("assessment", "clean")
            if assessment not in ("clean", "minor_concern", "looks_strong"):
                assessment = "clean"
            others.append(OtherPick(
                pick_number=op.get("pick_number", 0),
                assessment=assessment,
                note=op.get("note", ""),
            ))

        return SlateReview(
            vulnerable_picks=vulnerable,
            other_picks=others,
            slate_observations=data.get("slate_observations", []),
        )

    def write_reviews_to_bq(
        self,
        review: SlateReview,
        game_date: str,
        picks: list[dict],
    ) -> int:
        """Write reviews to BigQuery claude_pick_reviews table.

        Args:
            review: SlateReview from review_picks()
            game_date: YYYY-MM-DD
            picks: Original pick dicts (for player_lookup, system_id, game_id)

        Returns:
            Number of rows written
        """
        from shared.utils.bigquery_batch_writer import get_batch_writer

        table_id = "nba-props-platform.nba_predictions.claude_pick_reviews"
        writer = get_batch_writer(table_id)

        # Build pick lookup by 1-based index
        pick_by_number = {i + 1: p for i, p in enumerate(picks)}

        # Vulnerable picks
        vulnerable_numbers = set()
        for vp in review.vulnerable_picks:
            pick = pick_by_number.get(vp.pick_number, {})
            vulnerable_numbers.add(vp.pick_number)
            writer.add_record({
                "player_lookup": pick.get("player_lookup", ""),
                "game_id": pick.get("game_id", ""),
                "game_date": game_date,
                "system_id": pick.get("system_id", ""),
                "is_vulnerable": True,
                "vulnerability_rank": review.vulnerable_picks.index(vp) + 1,
                "assessment": "vulnerable",
                "risk_flags": vp.risk_flags,
                "reasoning": vp.reasoning,
                "prompt_version": review.prompt_version,
                "model_used": review.model_used,
                "input_tokens": review.input_tokens,
                "output_tokens": review.output_tokens,
                "cost_usd": review.cost_usd,
                "latency_ms": review.latency_ms,
                "review_status": "success",
                "created_at": datetime.utcnow().isoformat(),
            })

        # Other picks
        for op in review.other_picks:
            pick = pick_by_number.get(op.pick_number, {})
            if op.pick_number in vulnerable_numbers:
                continue  # Already written
            writer.add_record({
                "player_lookup": pick.get("player_lookup", ""),
                "game_id": pick.get("game_id", ""),
                "game_date": game_date,
                "system_id": pick.get("system_id", ""),
                "is_vulnerable": False,
                "vulnerability_rank": None,
                "assessment": op.assessment,
                "risk_flags": [],
                "reasoning": op.note,
                "prompt_version": review.prompt_version,
                "model_used": review.model_used,
                "input_tokens": review.input_tokens,
                "output_tokens": review.output_tokens,
                "cost_usd": review.cost_usd,
                "latency_ms": review.latency_ms,
                "review_status": "success",
                "created_at": datetime.utcnow().isoformat(),
            })

        written = writer.flush()
        logger.info(f"Wrote {written} reviews to {table_id}")
        return written
