#!/usr/bin/env python3
"""
Test the Claude pick reviewer (v2 adversarial) against Mar 8 picks.

Usage:
    # Dry run — print the prompt (no API call)
    PYTHONPATH=. python scripts/test_claude_review.py --dry-run

    # Live test
    PYTHONPATH=. python scripts/test_claude_review.py

    # Specify model
    PYTHONPATH=. python scripts/test_claude_review.py --model claude-haiku-4-5-20251001
"""

import argparse
import json
import logging
import sys

from ml.signals.claude_pick_reviewer import (
    ClaudePickReviewer,
    PickContext,
    SlateContext,
    build_slate_prompt,
    SYSTEM_PROMPT,
    PROMPT_VERSION,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


# ── Mar 8 picks with enriched context + actual outcomes ───────────────────────
# Season PPG and last 3 games are approximate based on known data

MAR_8_PICKS = [
    {
        "player_name": "Stephon Castle", "player_lookup": "stephoncastle",
        "team": "SAS", "opponent": "HOU", "is_home": True,
        "direction": "UNDER", "line_value": 15.5,
        "predicted_points": 11.9, "edge": 3.6,
        "player_tier": "role", "game_spread": 5.5,
        "season_ppg": 12.4, "season_minutes": 28.0,
        "last_3_games_pts": [18, 14, 10],
        "points_variance": 5.2, "trend_slope": -1.32,
        "over_under_last_5": "OUOOU",
        "actual_points": 23, "prediction_correct": False,
    },
    {
        "player_name": "Guerschon Yabusele", "player_lookup": "guerschonyabusele",
        "team": "CHI", "opponent": "SAC", "is_home": False,
        "direction": "OVER", "line_value": 11.5,
        "predicted_points": 17.8, "edge": 6.3,
        "player_tier": "bench", "game_spread": 2.5,
        "season_ppg": 10.8, "season_minutes": 22.0,
        "last_3_games_pts": [14, 12, 16],
        "points_variance": 6.1, "trend_slope": 0.96,
        "over_under_last_5": "OOUOO",
        "actual_points": 4, "prediction_correct": False,
    },
    {
        "player_name": "Devin Booker", "player_lookup": "devinbooker",
        "team": "PHX", "opponent": "CHA", "is_home": True,
        "direction": "UNDER", "line_value": 24.5,
        "predicted_points": 18.5, "edge": 6.0,
        "player_tier": "starter", "game_spread": 4.5,
        "season_ppg": 25.2, "season_minutes": 34.0,
        "last_3_games_pts": [24, 27, 34],
        "points_variance": 6.8, "trend_slope": 0.46,
        "over_under_last_5": "OOUOO",
        "actual_points": 30, "prediction_correct": False,
    },
    {
        "player_name": "Derrick White", "player_lookup": "derrickwhite",
        "team": "BOS", "opponent": "CLE", "is_home": False,
        "direction": "OVER", "line_value": 8.5,
        "predicted_points": 15.9, "edge": 7.4,
        "player_tier": "bench", "game_spread": 1.3,
        "season_ppg": 15.2, "season_minutes": 30.0,
        "last_3_games_pts": [16, 18, 12],
        "points_variance": 7.4, "trend_slope": 0.64,
        "prev_line": 16.5,  # KEY: massive line drop
        "over_under_last_5": "OUUOO",
        "actual_points": 6, "prediction_correct": False,
    },
    {
        "player_name": "Tyler Herro", "player_lookup": "tylerherro",
        "team": "MIA", "opponent": "DET", "is_home": True,
        "direction": "UNDER", "line_value": 23.5,
        "predicted_points": 19.6, "edge": 3.9,
        "player_tier": "starter", "game_spread": 1.5,
        "season_ppg": 23.8, "season_minutes": 34.5,
        "last_3_games_pts": [28, 25, 30],
        "points_variance": 7.1, "trend_slope": 2.71,
        "over_under_last_5": "OOOOU",
        "actual_points": 25, "prediction_correct": False,
    },
    {
        "player_name": "Deni Avdija", "player_lookup": "deniavdija",
        "team": "POR", "opponent": "IND", "is_home": False,
        "direction": "OVER", "line_value": 20.5,
        "predicted_points": 25.6, "edge": 5.1,
        "player_tier": "starter", "game_spread": 8.5,
        "season_ppg": 18.5, "season_minutes": 33.0,
        "last_3_games_pts": [15, 16, 22],
        "points_variance": 5.9, "trend_slope": -2.29,
        "over_under_last_5": "UUUOO",
        "actual_points": 18, "prediction_correct": False,
    },
    {
        "player_name": "Victor Wembanyama", "player_lookup": "victorwembanyama",
        "team": "SAS", "opponent": "HOU", "is_home": True,
        "direction": "UNDER", "line_value": 23.5,
        "predicted_points": 20.3, "edge": 3.2,
        "player_tier": "starter", "game_spread": 5.5,
        "season_ppg": 24.4, "season_minutes": 32.0,
        "last_3_games_pts": [28, 26, 31],
        "points_variance": 7.0, "trend_slope": 2.43,
        "over_under_last_5": "OOOOO",
        "actual_points": 29, "prediction_correct": False,
    },
    {
        "player_name": "Zion Williamson", "player_lookup": "zionwilliamson",
        "team": "NOP", "opponent": "WAS", "is_home": True,
        "direction": "UNDER", "line_value": 22.5,
        "predicted_points": 17.0, "edge": 5.5,
        "player_tier": "starter", "game_spread": 10.5,
        "season_ppg": 22.0, "season_minutes": 31.0,
        "last_3_games_pts": [20, 24, 22],
        "points_variance": 5.5, "trend_slope": -0.29,
        "over_under_last_5": "UOOUO",
        "actual_points": 20, "prediction_correct": True,
    },
    {
        "player_name": "Jayson Tatum", "player_lookup": "jaysontatum",
        "team": "BOS", "opponent": "CLE", "is_home": False,
        "direction": "OVER", "line_value": 18.5,
        "predicted_points": 21.7, "edge": 3.2,
        "player_tier": "starter", "game_spread": 1.0,
        "season_ppg": 27.1, "season_minutes": 36.0,
        "last_3_games_pts": [22, 19, 24],
        "points_variance": 6.3, "trend_slope": 0.0,
        "over_under_last_5": "UOUUU",
        "actual_points": 20, "prediction_correct": True,
    },
    {
        "player_name": "Will Riley", "player_lookup": "willriley",
        "team": "WAS", "opponent": "NOP", "is_home": False,
        "direction": "OVER", "line_value": 13.5,
        "predicted_points": 16.9, "edge": 3.4,
        "player_tier": "role", "game_spread": 9.5,
        "season_ppg": 12.5, "season_minutes": 25.0,
        "last_3_games_pts": [14, 12, 15],
        "points_variance": 5.0, "trend_slope": 0.04,
        "over_under_last_5": "OUOUO",
        "actual_points": 19, "prediction_correct": True,
    },
    {
        "player_name": "Amen Thompson", "player_lookup": "amenthompson",
        "team": "HOU", "opponent": "SAS", "is_home": False,
        "direction": "UNDER", "line_value": 16.5,
        "predicted_points": 12.7, "edge": 3.8,
        "player_tier": "role", "game_spread": 5.5,
        "season_ppg": 13.2, "season_minutes": 30.0,
        "last_3_games_pts": [18, 20, 16],
        "points_variance": 5.8, "trend_slope": 1.82,
        "over_under_last_5": "OOOOU",
        "actual_points": 23, "prediction_correct": False,
    },
    {
        "player_name": "Karl-Anthony Towns", "player_lookup": "karlanthonytowns",
        "team": "NYK", "opponent": "LAL", "is_home": True,
        "direction": "UNDER", "line_value": 18.5,
        "predicted_points": 15.2, "edge": 3.3,
        "player_tier": "starter", "game_spread": 3.0,
        "season_ppg": 25.1, "season_minutes": 34.0,
        "last_3_games_pts": [20, 16, 18],
        "points_variance": 7.2, "trend_slope": -0.82,
        "over_under_last_5": "UUUOU",
        "actual_points": 25, "prediction_correct": False,
    },
    {
        "player_name": "Precious Achiuwa", "player_lookup": "preciousachiuwa",
        "team": "SAC", "opponent": "CHI", "is_home": True,
        "direction": "OVER", "line_value": 14.5,
        "predicted_points": 17.6, "edge": 3.1,
        "player_tier": "role", "game_spread": 3.0,
        "season_ppg": 11.5, "season_minutes": 24.0,
        "last_3_games_pts": [16, 14, 18],
        "points_variance": 6.3, "trend_slope": 1.39,
        "over_under_last_5": "OOOUO",
        "actual_points": 13, "prediction_correct": False,
    },
    {
        "player_name": "Russell Westbrook", "player_lookup": "russellwestbrook",
        "team": "SAC", "opponent": "CHI", "is_home": True,
        "direction": "OVER", "line_value": 14.5,
        "predicted_points": 17.6, "edge": 3.2,
        "player_tier": "role", "game_spread": 3.0,
        "season_ppg": 12.8, "season_minutes": 22.0,
        "last_3_games_pts": [16, 18, 14],
        "points_variance": 7.5, "trend_slope": 1.75,
        "over_under_last_5": "OOUOO",
        "actual_points": 23, "prediction_correct": None,  # HOLD
    },
    {
        "player_name": "Isaac Okoro", "player_lookup": "isaacokoro",
        "team": "CHI", "opponent": "SAC", "is_home": False,
        "direction": "OVER", "line_value": 11.5,
        "predicted_points": 14.7, "edge": 3.2,
        "player_tier": "bench", "game_spread": 3.0,
        "season_ppg": 10.2, "season_minutes": 26.0,
        "last_3_games_pts": [8, 6, 10],
        "points_variance": 5.5, "trend_slope": -1.54,
        "over_under_last_5": "UUUOU",
        "actual_points": 9, "prediction_correct": False,
    },
    {
        "player_name": "Nique Clifford", "player_lookup": "niqueclifford",
        "team": "SAC", "opponent": "CHI", "is_home": True,
        "direction": "OVER", "line_value": 13.5,
        "predicted_points": 16.7, "edge": 3.2,
        "player_tier": "role", "game_spread": 3.0,
        "season_ppg": 11.0, "season_minutes": 22.0,
        "last_3_games_pts": [12, 14, 10],
        "points_variance": 5.8, "trend_slope": 0.14,
        "over_under_last_5": "OUOOU",
        "actual_points": 8, "prediction_correct": None,  # HOLD
    },
]


def build_pick_contexts(picks: list[dict]) -> list[PickContext]:
    """Convert raw pick dicts to PickContext objects with enriched data."""
    contexts = []
    for p in picks:
        slope = p.get("trend_slope", 0)
        if slope > 1.5:
            trend = "trending up strongly"
        elif slope > 0.3:
            trend = "trending up"
        elif slope < -1.5:
            trend = "trending down strongly"
        elif slope < -0.3:
            trend = "trending down"
        else:
            trend = "stable"

        contexts.append(PickContext(
            player_name=p["player_name"],
            team=p["team"],
            opponent=p["opponent"],
            is_home=p.get("is_home", False),
            game_time="",
            line_value=p["line_value"],
            predicted_points=p["predicted_points"],
            edge=p["edge"],
            direction=p["direction"],
            player_tier=p.get("player_tier"),
            rank=p.get("rank"),
            is_rescued=p.get("is_rescued", False),
            is_ultra=p.get("is_ultra", False),
            game_spread=p.get("game_spread"),
            season_ppg=p.get("season_ppg"),
            season_minutes=p.get("season_minutes"),
            last_3_games_pts=p.get("last_3_games_pts", []),
            points_variance=p.get("points_variance"),
            scoring_trend=trend,
            prev_line=p.get("prev_line"),
            over_under_last_5=p.get("over_under_last_5"),
        ))
    return contexts


def build_slate_context(picks: list[dict], game_date: str) -> SlateContext:
    """Build slate context from picks."""
    over_count = sum(1 for p in picks if p["direction"] == "OVER")
    under_count = sum(1 for p in picks if p["direction"] == "UNDER")

    game_counts = {}
    for p in picks:
        matchup = tuple(sorted([p["team"], p["opponent"]]))
        game_counts[matchup] = game_counts.get(matchup, 0) + 1

    same_game = {f"{k[0]}-{k[1]}": v for k, v in game_counts.items() if v > 1}

    return SlateContext(
        game_date=game_date,
        total_games_today=8,
        total_picks=len(picks),
        over_count=over_count,
        under_count=under_count,
        picks_from_same_game=same_game,
    )


def print_outcomes(picks: list[dict]):
    """Print actual outcomes for comparison."""
    print("\n" + "=" * 70)
    print("ACTUAL OUTCOMES (Claude doesn't see these)")
    print("=" * 70)
    wins = losses = holds = 0
    for i, p in enumerate(picks):
        correct = p.get("prediction_correct")
        actual = p.get("actual_points", "?")
        if correct is True:
            result = "WIN"
            wins += 1
        elif correct is False:
            result = "LOSS"
            losses += 1
        else:
            result = "HOLD"
            holds += 1
        print(f"  #{i+1:2d} {p['player_name']:25s} {p['direction']:5s} {p['line_value']:5.1f} → {actual:>3} {result}")

    print(f"\nRecord: {wins}-{losses} ({holds} holds) = {wins/(wins+losses)*100:.1f}% HR")


def main():
    parser = argparse.ArgumentParser(description="Test Claude pick reviewer v2")
    parser.add_argument("--dry-run", action="store_true", help="Print prompt only")
    parser.add_argument("--model", default=None, help="Claude model to use")
    args = parser.parse_args()

    game_date = "2026-03-08"
    picks = MAR_8_PICKS
    pick_contexts = build_pick_contexts(picks)
    slate = build_slate_context(picks, game_date)

    system = SYSTEM_PROMPT.replace("{game_date}", game_date)
    user_prompt = build_slate_prompt(pick_contexts, slate)

    if args.dry_run:
        print("=" * 70)
        print(f"SYSTEM PROMPT (v{PROMPT_VERSION})")
        print("=" * 70)
        print(system)
        print("\n" + "=" * 70)
        print("USER PROMPT")
        print("=" * 70)
        print(user_prompt)
        print(f"\n[~{len(system.split()) + len(user_prompt.split())} words]")
        print_outcomes(picks)
        return

    # Live API call
    model = args.model or "claude-haiku-4-5-20251001"
    print(f"Calling Claude ({model}) for {len(picks)} picks [v{PROMPT_VERSION}]...")

    reviewer = ClaudePickReviewer(model=model)
    review = reviewer.review_picks(pick_contexts, slate)

    # Print results
    print(f"\n{'=' * 70}")
    print(f"ADVERSARIAL REVIEW — {game_date} ({review.model_used})")
    print(f"Prompt v{PROMPT_VERSION} | {review.input_tokens} in / {review.output_tokens} out | ${review.cost_usd:.4f} | {review.latency_ms}ms")
    print(f"{'=' * 70}\n")

    # Vulnerable picks
    print("VULNERABLE PICKS (Claude's bottom 3):")
    for i, vp in enumerate(review.vulnerable_picks):
        pick_data = picks[vp.pick_number - 1] if 0 < vp.pick_number <= len(picks) else {}
        name = pick_data.get("player_name", f"Pick #{vp.pick_number}")
        print(f"  #{i+1} vulnerable: Pick #{vp.pick_number} — {name}")
        if vp.risk_flags:
            print(f"     Flags: {', '.join(vp.risk_flags)}")
        print(f"     {vp.reasoning}")
        print()

    # Other picks
    print("OTHER PICKS:")
    for op in sorted(review.other_picks, key=lambda x: x.pick_number):
        pick_data = picks[op.pick_number - 1] if 0 < op.pick_number <= len(picks) else {}
        name = pick_data.get("player_name", f"Pick #{op.pick_number}")
        note = f" — {op.note}" if op.note else ""
        print(f"  #{op.pick_number:2d} {name:25s} [{op.assessment}]{note}")

    # Slate observations
    if review.slate_observations:
        print(f"\nSLATE OBSERVATIONS:")
        for obs in review.slate_observations:
            print(f"  • {obs}")

    # Show outcomes
    print_outcomes(picks)

    # Correlation
    print("\n" + "=" * 70)
    print("VALIDATION: Did Claude's bottom 3 actually lose?")
    print("=" * 70)
    vulnerable_numbers = {vp.pick_number for vp in review.vulnerable_picks}
    vuln_wins = vuln_losses = other_wins = other_losses = 0

    for i, p in enumerate(picks):
        correct = p.get("prediction_correct")
        if correct is None:
            continue
        if (i + 1) in vulnerable_numbers:
            if correct:
                vuln_wins += 1
            else:
                vuln_losses += 1
        else:
            if correct:
                other_wins += 1
            else:
                other_losses += 1

    vuln_total = vuln_wins + vuln_losses
    other_total = other_wins + other_losses
    print(f"  Vulnerable (bottom 3): {vuln_wins}-{vuln_losses} ({vuln_wins/vuln_total*100:.0f}% HR)" if vuln_total else "  Vulnerable: N/A")
    print(f"  Other picks (top 13):  {other_wins}-{other_losses} ({other_wins/other_total*100:.0f}% HR)" if other_total else "  Other: N/A")
    if vuln_total and other_total:
        gap = (other_wins / other_total - vuln_wins / vuln_total) * 100
        print(f"  Gap: {gap:+.0f}pp (need +10pp sustained over 60 days)")
    print(f"\n  [N=1 day — draw NO conclusions. Need 60+ days of data.]")


if __name__ == "__main__":
    main()
