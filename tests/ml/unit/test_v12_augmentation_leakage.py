"""
Regression test for P0-2 — V12 season_stats augmentation temporal leakage.

Background (April audit T2-3 / offseason roadmap P0-2):
`augment_v12_features` in ml/experiments/quick_retrain.py computed season
averages with `SELECT AVG(points) ... GROUP BY player_lookup` — ONE average
over the whole window, assigned to every game. A game on Nov 1 therefore got a
season average that already included its own December/January future, leaking
look-ahead information into `deviation_from_avg_last3` and
`consecutive_games_below_avg`.

The fix computes season stats per-row with a window frame of
`ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING` — each game sees only that
player's strictly-earlier games.

These tests lock that invariant: the leak-free per-row average must equal an
independent "strictly-before-X" reference, and must differ from the old
full-window average (so a regression back to `GROUP BY` is caught).

Path: tests/ml/unit/test_v12_augmentation_leakage.py
Created: 2026-05-19 (P0-2)
"""

import pathlib

import numpy as np
import pandas as pd
import pytest


QUICK_RETRAIN = (
    pathlib.Path(__file__).resolve().parents[3]
    / "ml" / "experiments" / "quick_retrain.py"
)


@pytest.fixture
def player_games():
    """Synthetic per-player game log with deliberately non-constant scoring."""
    rows = [
        # player, game_date, points
        ("alice", "2025-11-01", 10.0),
        ("alice", "2025-11-04", 20.0),
        ("alice", "2025-11-07", 30.0),
        ("alice", "2025-11-10", 12.0),
        ("alice", "2025-11-13", 28.0),
        ("bob", "2025-11-02", 5.0),
        ("bob", "2025-11-05", 7.0),
        ("bob", "2025-11-08", 9.0),
    ]
    df = pd.DataFrame(rows, columns=["player_lookup", "game_date", "points"])
    df["game_date"] = pd.to_datetime(df["game_date"])
    return df.sort_values(["player_lookup", "game_date"]).reset_index(drop=True)


def _per_row_season_avg(df):
    """Mirror the FIXED SQL: AVG(points) OVER (PARTITION BY player
    ORDER BY game_date ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)."""
    return (
        df.groupby("player_lookup")["points"]
        .apply(lambda s: s.expanding().mean().shift(1))
        .reset_index(level=0, drop=True)
    )


def _old_full_window_avg(df):
    """Mirror the OLD leaky SQL: AVG(points) ... GROUP BY player_lookup."""
    means = df.groupby("player_lookup")["points"].transform("mean")
    return means


def _strictly_before_reference(df):
    """Independent reference: for each row, mean of that player's points in
    games with a strictly-earlier game_date. This is the no-leak definition."""
    out = []
    for idx, row in df.iterrows():
        prior = df[
            (df["player_lookup"] == row["player_lookup"])
            & (df["game_date"] < row["game_date"])
        ]["points"]
        out.append(prior.mean() if len(prior) else np.nan)
    return pd.Series(out, index=df.index)


def test_per_row_avg_matches_strictly_before_reference(player_games):
    """The fixed per-row season average uses ONLY strictly-earlier games."""
    per_row = _per_row_season_avg(player_games)
    reference = _strictly_before_reference(player_games)

    # First game of each player has no prior history -> NaN in both.
    both_nan = per_row.isna() & reference.isna()
    comparable = ~both_nan
    assert comparable.sum() > 0, "fixture must contain non-first games"
    np.testing.assert_allclose(
        per_row[comparable].to_numpy(),
        reference[comparable].to_numpy(),
        atol=1e-9,
        err_msg="per-row season avg must equal the strictly-before-X reference",
    )


def test_old_group_by_avg_leaks_future_games(player_games):
    """The old GROUP BY average is a single leaked number repeated for every
    game; the leak-free per-row average varies game to game. This structural
    signature is the unambiguous proof of the leak and a guard against a
    regression back to GROUP BY."""
    old = _old_full_window_avg(player_games)
    per_row = _per_row_season_avg(player_games)

    for player in player_games["player_lookup"].unique():
        mask = (player_games["player_lookup"] == player).to_numpy()
        old_vals = old[mask]
        per_row_vals = per_row[mask].dropna()

        # Old method: one value folded over the whole window (the leak).
        assert old_vals.nunique() == 1, (
            f"old GROUP BY avg must be constant across {player}'s games"
        )
        # Leak-free method: changes as history accumulates.
        assert per_row_vals.nunique() > 1, (
            f"per-row season avg should vary across {player}'s games"
        )
        # The leaked constant differs from the leak-free value on the first
        # game that has prior history.
        assert abs(per_row_vals.iloc[0] - old_vals.iloc[0]) > 0.1, (
            f"old avg must differ from the leak-free value on {player}'s "
            "first game with history"
        )


def test_quick_retrain_sql_uses_per_row_window():
    """Backstop: the augment_v12_features SQL must compute season stats with a
    per-row window frame, not a bare GROUP BY aggregate."""
    src = QUICK_RETRAIN.read_text()
    assert "augment_v12_features" in src

    # The fixed form: windowed per-row season average.
    assert "AVG(points) OVER w AS season_avg" in src, (
        "season_stats must use a per-row AVG(...) OVER window (P0-2 fix)"
    )
    assert "ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING" in src

    # The leaky form must be gone.
    assert "AVG(points) as season_avg" not in src, (
        "the old leaky `AVG(points) as season_avg` GROUP BY form must not return"
    )
