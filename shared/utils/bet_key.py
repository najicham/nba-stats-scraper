"""Canonical identity for a single wager.

A `bet_key` names the BET, not the model that nominated it. It deliberately
EXCLUDES `system_id`: when three models nominate the same player, direction and
line, that is one bet, not three. Joining `signal_best_bets_picks` to
`prediction_accuracy` on (player, date) alone — without direction and line —
is what inflated the 2025-26 published record 3.7x (415-235 was really 175
picks counted 3.7 times).

The SQL form must stay byte-identical to this one:

    CONCAT(
      IFNULL(game_id,''), '|', IFNULL(player_lookup,''), '|',
      IFNULL(recommendation,''), '|',
      IFNULL(FORMAT('%.1f', CAST(line_value AS FLOAT64)), '')
    )
"""

from typing import Optional


def build_bet_key(
    game_id: Optional[str],
    player_lookup: Optional[str],
    recommendation: Optional[str],
    line_value: Optional[float],
) -> str:
    """Build the canonical bet identity string.

    Missing components render as empty segments rather than raising, so a
    partially-populated pick still produces a stable, comparable key.
    """
    try:
        line = '' if line_value is None else f'{float(line_value):.1f}'
    except (TypeError, ValueError):
        line = ''
    return '|'.join([
        game_id or '',
        player_lookup or '',
        recommendation or '',
        line,
    ])
