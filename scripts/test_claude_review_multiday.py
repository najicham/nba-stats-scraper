#!/usr/bin/env python3
"""
Test Claude v2 adversarial reviewer across multiple days.

Usage:
    PYTHONPATH=. python scripts/test_claude_review_multiday.py
"""

import json
import logging
import sys
import time

from ml.signals.claude_pick_reviewer import (
    ClaudePickReviewer,
    PickContext,
    SlateContext,
    build_slate_prompt,
    SYSTEM_PROMPT,
    PROMPT_VERSION,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# ── Multi-day test data (from BQ) ────────────────────────────────────────────

DAYS = {
    "2026-03-05": {  # GOOD day: 8-3 (72.7%)
        "games_today": 7,
        "picks": [
            {"player_name": "Austin Reaves", "team": "LAL", "opponent": "DEN", "is_home": False,
             "direction": "UNDER", "line_value": 19.5, "season_ppg": 23.7, "season_minutes": 33.0,
             "last_3_games_pts": [15, 12, 18], "points_variance": 10.3,
             "actual_points": 16, "prediction_correct": True},
            {"player_name": "Bilal Coulibaly", "team": "WAS", "opponent": "UTA", "is_home": True,
             "direction": "OVER", "line_value": 12.5, "season_ppg": 10.4, "season_minutes": 26.0,
             "last_3_games_pts": [6, 23, 14], "points_variance": 5.0,
             "actual_points": 17, "prediction_correct": True},
            {"player_name": "Cade Cunningham", "team": "DET", "opponent": "SAS", "is_home": False,
             "direction": "UNDER", "line_value": 25.5, "season_ppg": 25.6, "season_minutes": 35.0,
             "last_3_games_pts": [10, 29, 25], "points_variance": 8.4,
             "actual_points": 26, "prediction_correct": False},
            {"player_name": "Devin Booker", "team": "PHX", "opponent": "CHI", "is_home": True,
             "direction": "OVER", "line_value": 24.5, "season_ppg": 24.3, "season_minutes": 33.0,
             "last_3_games_pts": [17, 5, 19], "points_variance": 7.4,
             "actual_points": 27, "prediction_correct": True},
            {"player_name": "Grayson Allen", "team": "PHX", "opponent": "CHI", "is_home": True,
             "direction": "OVER", "line_value": 17.5, "season_ppg": 17.8, "season_minutes": 30.0,
             "last_3_games_pts": [18, 28, 14], "points_variance": 7.8,
             "actual_points": 21, "prediction_correct": True},
            {"player_name": "Gui Santos", "team": "GSW", "opponent": "HOU", "is_home": False,
             "direction": "OVER", "line_value": 12.5, "season_ppg": 7.0, "season_minutes": 17.0,
             "last_3_games_pts": [5, 14, 17], "points_variance": 5.9,
             "actual_points": 14, "prediction_correct": True},
            {"player_name": "Jalen Duren", "team": "DET", "opponent": "SAS", "is_home": False,
             "direction": "UNDER", "line_value": 18.5, "season_ppg": 19.1, "season_minutes": 29.0,
             "last_3_games_pts": [24, 16, 33], "points_variance": 6.7,
             "actual_points": 7, "prediction_correct": True},
            {"player_name": "Kevin Durant", "team": "HOU", "opponent": "GSW", "is_home": True,
             "direction": "UNDER", "line_value": 25.5, "season_ppg": 26.1, "season_minutes": 36.0,
             "last_3_games_pts": [30, 32, 40], "points_variance": 6.8,
             "actual_points": 23, "prediction_correct": True},
            {"player_name": "Scottie Barnes", "team": "TOR", "opponent": "MIN", "is_home": False,
             "direction": "OVER", "line_value": 17.5, "season_ppg": 18.7, "season_minutes": 34.0,
             "last_3_games_pts": [14, 18, 15], "points_variance": 5.7,
             "actual_points": 16, "prediction_correct": False},
            {"player_name": "Tre Johnson", "team": "WAS", "opponent": "UTA", "is_home": True,
             "direction": "OVER", "line_value": 13.5, "season_ppg": 12.1, "season_minutes": 24.0,
             "last_3_games_pts": [9, 5, 8], "points_variance": 5.1,
             "actual_points": 15, "prediction_correct": True},
            {"player_name": "Tyler Herro", "team": "MIA", "opponent": "BKN", "is_home": True,
             "direction": "UNDER", "line_value": 21.5, "season_ppg": 21.1, "season_minutes": 30.0,
             "last_3_games_pts": [22, 18, 25], "points_variance": 3.9,
             "actual_points": 25, "prediction_correct": False},
        ]
    },
    "2026-03-04": {  # MEDIOCRE day: 3-4 (42.9%)
        "games_today": 5,
        "picks": [
            {"player_name": "Brice Sensabaugh", "team": "UTA", "opponent": "PHI", "is_home": False,
             "direction": "OVER", "line_value": 15.5, "season_ppg": 12.7, "season_minutes": 22.0,
             "last_3_games_pts": [7, 8, 10], "points_variance": 8.5,
             "actual_points": 7, "prediction_correct": False},
            {"player_name": "Isaiah Collier", "team": "UTA", "opponent": "PHI", "is_home": False,
             "direction": "OVER", "line_value": 12.5, "season_ppg": 11.2, "season_minutes": 26.0,
             "last_3_games_pts": [18, 10, 21], "points_variance": 5.8,
             "actual_points": 18, "prediction_correct": True},
            {"player_name": "Isaiah Joe", "team": "OKC", "opponent": "NYK", "is_home": False,
             "direction": "OVER", "line_value": 9.5, "season_ppg": 10.7, "season_minutes": 21.0,
             "last_3_games_pts": [4, 19, 14], "points_variance": 6.7,
             "actual_points": 4, "prediction_correct": False},
            {"player_name": "Jalen Johnson", "team": "ATL", "opponent": "MIL", "is_home": False,
             "direction": "OVER", "line_value": 21.5, "season_ppg": 23.1, "season_minutes": 35.0,
             "last_3_games_pts": [20, 8, 5], "points_variance": 8.0,
             "actual_points": 20, "prediction_correct": False},
            {"player_name": "Jaylen Wells", "team": "MEM", "opponent": "POR", "is_home": True,
             "direction": "OVER", "line_value": 12.5, "season_ppg": 12.8, "season_minutes": 27.0,
             "last_3_games_pts": [24, 19, 18], "points_variance": 5.6,
             "actual_points": 24, "prediction_correct": True},
            {"player_name": "Keyonte George", "team": "UTA", "opponent": "PHI", "is_home": False,
             "direction": "OVER", "line_value": 21.5, "season_ppg": 24.4, "season_minutes": 34.0,
             "last_3_games_pts": [30, 36, 17], "points_variance": 9.2,
             "actual_points": 30, "prediction_correct": True},
            {"player_name": "Scoot Henderson", "team": "POR", "opponent": "MEM", "is_home": False,
             "direction": "OVER", "line_value": 13.5, "season_ppg": 12.4, "season_minutes": 23.0,
             "last_3_games_pts": [8, 11, 8], "points_variance": 3.6,
             "actual_points": 8, "prediction_correct": False},
        ]
    },
}


def build_pick_context(p: dict) -> PickContext:
    """Build PickContext from pick dict."""
    ppg = p.get("season_ppg")
    last3 = p.get("last_3_games_pts", [])

    # Derive trend from last 3 games
    if len(last3) >= 3:
        avg_recent = sum(last3) / len(last3)
        if ppg and avg_recent > ppg * 1.15:
            trend = "trending up"
        elif ppg and avg_recent < ppg * 0.85:
            trend = "trending down"
        else:
            trend = "stable"
    else:
        trend = None

    return PickContext(
        player_name=p["player_name"],
        team=p["team"],
        opponent=p["opponent"],
        is_home=p.get("is_home", False),
        game_time="",
        line_value=p["line_value"],
        predicted_points=p.get("predicted_points", 0),
        edge=p.get("edge", 0),
        direction=p["direction"],
        season_ppg=p.get("season_ppg"),
        season_minutes=p.get("season_minutes"),
        last_3_games_pts=p.get("last_3_games_pts", []),
        points_variance=p.get("points_variance"),
        scoring_trend=trend,
        prev_line=p.get("prev_line"),
        game_spread=p.get("game_spread"),
    )


def run_day(reviewer, game_date: str, day_data: dict):
    """Run adversarial review for one day and print results."""
    picks = day_data["picks"]
    contexts = [build_pick_context(p) for p in picks]

    over_count = sum(1 for p in picks if p["direction"] == "OVER")
    under_count = sum(1 for p in picks if p["direction"] == "UNDER")

    slate = SlateContext(
        game_date=game_date,
        total_games_today=day_data["games_today"],
        total_picks=len(picks),
        over_count=over_count,
        under_count=under_count,
    )

    review = reviewer.review_picks(contexts, slate)

    # Print
    wins = sum(1 for p in picks if p.get("prediction_correct") is True)
    losses = sum(1 for p in picks if p.get("prediction_correct") is False)
    hr = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0

    print(f"\n{'='*70}")
    print(f"{game_date} — Actual: {wins}-{losses} ({hr:.0f}% HR) | "
          f"{review.input_tokens} in / {review.output_tokens} out | ${review.cost_usd:.4f} | {review.latency_ms}ms")
    print(f"{'='*70}")

    # Vulnerable picks
    vulnerable_numbers = set()
    print("\nVULNERABLE (bottom 3):")
    for i, vp in enumerate(review.vulnerable_picks):
        vulnerable_numbers.add(vp.pick_number)
        pick_data = picks[vp.pick_number - 1] if 0 < vp.pick_number <= len(picks) else {}
        name = pick_data.get("player_name", f"#{vp.pick_number}")
        actual = pick_data.get("actual_points", "?")
        correct = pick_data.get("prediction_correct")
        result = "WIN" if correct is True else "LOSS" if correct is False else "?"
        flags = ", ".join(vp.risk_flags) if vp.risk_flags else "none"
        print(f"  #{vp.pick_number} {name:25s} → actual {actual:>3} {result:4s} | {flags}")
        print(f"     {vp.reasoning}")

    # Other picks summary
    print("\nOTHER PICKS:")
    for op in sorted(review.other_picks, key=lambda x: x.pick_number):
        pick_data = picks[op.pick_number - 1] if 0 < op.pick_number <= len(picks) else {}
        name = pick_data.get("player_name", f"#{op.pick_number}")
        actual = pick_data.get("actual_points", "?")
        correct = pick_data.get("prediction_correct")
        result = "WIN" if correct is True else "LOSS" if correct is False else "?"
        note = f" — {op.note}" if op.note else ""
        print(f"  #{op.pick_number:2d} {name:25s} → {actual:>3} {result:4s} [{op.assessment}]{note}")

    if review.slate_observations:
        print("\nSLATE:")
        for obs in review.slate_observations:
            print(f"  • {obs}")

    # Validation
    vuln_wins = vuln_losses = other_wins = other_losses = 0
    for i, p in enumerate(picks):
        correct = p.get("prediction_correct")
        if correct is None:
            continue
        if (i + 1) in vulnerable_numbers:
            if correct: vuln_wins += 1
            else: vuln_losses += 1
        else:
            if correct: other_wins += 1
            else: other_losses += 1

    vuln_total = vuln_wins + vuln_losses
    other_total = other_wins + other_losses
    vuln_hr = vuln_wins / vuln_total * 100 if vuln_total else 0
    other_hr = other_wins / other_total * 100 if other_total else 0
    gap = other_hr - vuln_hr

    print(f"\n  Bottom 3: {vuln_wins}-{vuln_losses} ({vuln_hr:.0f}% HR)")
    print(f"  Others:   {other_wins}-{other_losses} ({other_hr:.0f}% HR)")
    print(f"  Gap: {gap:+.0f}pp")

    return {
        "date": game_date,
        "vuln_wins": vuln_wins, "vuln_losses": vuln_losses,
        "other_wins": other_wins, "other_losses": other_losses,
    }


def main():
    reviewer = ClaudePickReviewer(model="claude-haiku-4-5-20251001")
    results = []

    for game_date in sorted(DAYS.keys()):
        result = run_day(reviewer, game_date, DAYS[game_date])
        results.append(result)
        time.sleep(1)  # Brief pause between API calls

    # Aggregate
    print(f"\n{'='*70}")
    print("AGGREGATE (Mar 4 + Mar 5)")
    print(f"{'='*70}")
    total_vuln_w = sum(r["vuln_wins"] for r in results)
    total_vuln_l = sum(r["vuln_losses"] for r in results)
    total_other_w = sum(r["other_wins"] for r in results)
    total_other_l = sum(r["other_losses"] for r in results)

    vuln_t = total_vuln_w + total_vuln_l
    other_t = total_other_w + total_other_l
    vuln_hr = total_vuln_w / vuln_t * 100 if vuln_t else 0
    other_hr = total_other_w / other_t * 100 if other_t else 0

    print(f"  Bottom 3: {total_vuln_w}-{total_vuln_l} ({vuln_hr:.0f}% HR)")
    print(f"  Others:   {total_other_w}-{total_other_l} ({other_hr:.0f}% HR)")
    print(f"  Gap: {other_hr - vuln_hr:+.0f}pp")
    print(f"\n  Total cost: ${reviewer.total_cost:.4f}")
    print(f"  [Still tiny N — need 60+ days for conclusions]")


if __name__ == "__main__":
    main()
