"""Break-even hit rate for NBA player prop bets.

Break-even is NOT a constant — it is a function of EXECUTION. The system historically
hardcoded ``BREAKEVEN_HR = 52.4`` in eight production/monitoring modules while the
discovery scripts under ``scripts/nba/training/discovery/`` independently hardcoded
``REAL_BE = 0.535``. Both numbers are correct; they describe different bettors.

Measurement (2026-08-19, 5 seasons of BettingPros two-sided prices at the consensus
number, simultaneous cross-book snapshot): the mean payout per book is **0.870**, and
it is remarkably stable season over season (0.8803 / 0.8756 / 0.8764 / 0.8754 / 0.8701
for 2021-22 → 2025-26). 1 / (1 + 0.870) = 0.535 — which is exactly the constant the
discovery scripts already use, arrived at independently.

    execution                         mean payout   break-even HR
    ------------------------------    -----------   -------------
    one average book                     0.870         53.5%
    best of DK / FD / MGM / Caesars      0.910         52.4%
    best of all ~10 books (2025-26)      0.942         51.5%

The long-assumed "-110 → 52.4%" is therefore only right if you shop the four majors.
Bet at a single book and the true bar is a full point higher; shop ten books and it is
a point lower. Reporting ROI at a flat -110 overstates realized ROI by 3.1-4.5 pp,
worst on high-edge UNDER.

OWNER DECISION 2026-08-19: execution is **best of the four majors**, so
``DEFAULT_BREAKEVEN_HR`` is 52.4 and stays there.

That settles a real disagreement. Production modules used 52.4 while the
discovery scripts under ``scripts/nba/training/discovery/`` independently used
0.535, so any signal or model sitting in the 52.4-53.5 band was scored profitable
by one half of the system and unprofitable by the other. Both now import from
here. If the execution assumption changes, change it in this file only.

IMPORTANT — changing ``DEFAULT`` changes gating behavior everywhere (signal decay,
model health, promotion gates, drift detection). Raising it to 53.5 is the honest
bar if you stop shopping the majors, but it will reclassify everything in that
band as unprofitable.

Override without a code change via ``NBA_BREAKEVEN_HR`` (percent, e.g. "53.5").
"""

import os

# --- Execution-dependent break-even hit rates (percent) -----------------------

#: One average book. The honest bar if you do not line-shop.
BREAKEVEN_HR_SINGLE_BOOK = 53.5

#: Best price across DraftKings / FanDuel / BetMGM / Caesars. The realistic target
#: for a disciplined bettor holding the major accounts.
BREAKEVEN_HR_MAJORS = 52.4

#: Best price across ~10 books incl. Fliff / PrizePicks / ESPN Bet / Hard Rock.
#: Attainable but adversely selected — by construction you always take the outlier
#: quote, which is the one most likely to be stale and to get limited.
BREAKEVEN_HR_WIDE = 51.5

#: Default used by gates and monitors. Historical value — see module docstring
#: before changing.
DEFAULT_BREAKEVEN_HR = float(os.getenv('NBA_BREAKEVEN_HR', BREAKEVEN_HR_MAJORS))

#: Back-compat alias for modules that imported a bare ``BREAKEVEN_HR``.
BREAKEVEN_HR = DEFAULT_BREAKEVEN_HR


def breakeven_hr(execution: str = 'majors') -> float:
    """Return the break-even hit rate (percent) for a given execution assumption.

    Args:
        execution: one of ``'single_book'``, ``'majors'``, ``'wide'``.

    Raises:
        ValueError: on an unknown execution mode.
    """
    table = {
        'single_book': BREAKEVEN_HR_SINGLE_BOOK,
        'majors': BREAKEVEN_HR_MAJORS,
        'wide': BREAKEVEN_HR_WIDE,
    }
    if execution not in table:
        raise ValueError(
            f"Unknown execution mode {execution!r}; expected one of {sorted(table)}"
        )
    return table[execution]


def roi_at_payout(hit_rate_pct: float, payout: float = 0.870) -> float:
    """Expected ROI (percent) at a given hit rate and average decimal payout.

    ``payout`` is the profit per 1 unit staked on a win (0.909 == -110).
    Defaults to the measured single-book mean of 0.870 rather than the assumed
    -110, because assuming -110 is exactly the error this module exists to correct.
    """
    p = hit_rate_pct / 100.0
    return 100.0 * (p * payout - (1.0 - p))
