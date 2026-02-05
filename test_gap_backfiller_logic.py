#!/usr/bin/env python3
"""
Test script for scraper_gap_backfiller health check logic.

Tests the decision tree for when to skip health checks based on:
- Gap age (0-1 days = recent)
- Scraper type (post-game scrapers)
"""

from datetime import datetime, timedelta, date

# Constants from main.py
POST_GAME_SCRAPERS = {'nbac_gamebook_pdf', 'nbac_player_boxscore'}

def test_health_check_decision(scraper_name: str, gap_date: date, today: date) -> tuple[str, str]:
    """
    Simulate the health check decision logic.

    Returns:
        (decision, reason) tuple
        decision: "skip" or "run"
        reason: explanation
    """
    gap_age_days = (today - gap_date).days

    if gap_age_days <= 1:
        return ("skip", f"skipped_recent_gap (age={gap_age_days} days)")
    elif scraper_name in POST_GAME_SCRAPERS:
        return ("skip", f"skipped_post_game_scraper")
    else:
        return ("run", f"normal_health_check (age={gap_age_days} days)")


def run_tests():
    """Run test scenarios."""
    print("=" * 80)
    print("Health Check Decision Logic Tests")
    print("=" * 80)

    # Simulate running at midnight on Feb 5, 2026
    today = date(2026, 2, 5)
    print(f"\nToday's date: {today} (simulating midnight run)")
    print()

    test_cases = [
        # (scraper_name, gap_date, expected_decision, scenario_description)

        # Test Case 1: Post-game scraper with yesterday's gap (Feb 4)
        ("nbac_gamebook_pdf", date(2026, 2, 4), "skip",
         "Bug Case: Yesterday's gamebook gap at midnight"),

        # Test Case 2: Post-game scraper with today's gap (Feb 5)
        ("nbac_gamebook_pdf", date(2026, 2, 5), "skip",
         "Today's gamebook gap (shouldn't happen, but handle it)"),

        # Test Case 3: Post-game scraper with 3-day old gap
        ("nbac_gamebook_pdf", date(2026, 2, 2), "skip",
         "3-day old gamebook gap (still skip - post-game scraper)"),

        # Test Case 4: Non-post-game scraper with yesterday's gap
        ("nbac_schedule", date(2026, 2, 4), "skip",
         "Yesterday's schedule gap (recent, skip health check)"),

        # Test Case 5: Non-post-game scraper with 3-day old gap
        ("nbac_schedule", date(2026, 2, 2), "run",
         "3-day old schedule gap (old enough to health check)"),

        # Test Case 6: Player boxscore (post-game) with yesterday's gap
        ("nbac_player_boxscore", date(2026, 2, 4), "skip",
         "Yesterday's player boxscore gap (post-game scraper)"),

        # Test Case 7: Non-post-game scraper with today's gap
        ("nbac_team_data", date(2026, 2, 5), "skip",
         "Today's team data gap (recent, skip)"),
    ]

    print(f"{'#':<3} {'Scraper':<25} {'Gap Date':<12} {'Age':<4} {'Decision':<6} {'Reason':<40}")
    print("-" * 100)

    for i, (scraper_name, gap_date, expected_decision, description) in enumerate(test_cases, 1):
        decision, reason = test_health_check_decision(scraper_name, gap_date, today)
        gap_age = (today - gap_date).days

        # Check if decision matches expectation
        status = "✓" if decision == expected_decision else "✗"

        print(f"{i:<3} {scraper_name:<25} {gap_date!s:<12} {gap_age:<4} {decision:<6} {reason:<40}")
        print(f"    {status} {description}")

        if decision != expected_decision:
            print(f"    ERROR: Expected '{expected_decision}', got '{decision}'")
        print()

    print("=" * 80)
    print("Key Insight:")
    print("=" * 80)
    print("At midnight on Feb 5:")
    print("  - Feb 4 gaps are 1 day old → SKIP health check (recent gap)")
    print("  - Feb 5 gaps are 0 days old → SKIP health check (same day)")
    print("  - Feb 2 gaps are 3 days old → RUN health check (unless post-game scraper)")
    print()
    print("Post-game scrapers (gamebook, player_boxscore):")
    print("  - ALWAYS skip health check (can't test with today's date)")
    print("  - Go straight to backfill attempt")
    print()


if __name__ == "__main__":
    run_tests()
