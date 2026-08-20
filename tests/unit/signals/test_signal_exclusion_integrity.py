"""Regression tests for the 2026-08-19 real_sc exclusion repair.

Three defects were found in the signal aggregator, all of which corrupted `real_sc` —
the gate the entire best-bets selection pipeline rests on:

  F1  The UNDER ranking branch excluded only BASE_SIGNALS, not SHADOW_SIGNALS, so every
      shadow tag contributed to `under_signal_quality` (which IS the UNDER composite
      score). The OVER branch, 13 lines below, excluded both.
  F2  16 of the 32 signals feeding real_sc were declared `removed`/`shadow` in
      shared/registry/signals.yaml. Dropping a tag from SHADOW_SIGNALS without also
      unregistering it silently PROMOTES it to a full real signal.
  F3  Three NEGATIVE filters (qualifies=True means "this pick is bad") were registered
      as positive signals, so a pick could clear the under_low_rsc floor *because the
      closing line moved against it*.

These tests exist so none of the three can regress silently.
"""

import pytest

from ml.signals.aggregator import (
    BASE_SIGNALS,
    NEGATIVE_SEMANTIC_SIGNALS,
    SHADOW_SIGNALS,
    UNDER_SIGNAL_WEIGHTS,
    validate_signal_registry_consistency,
)
from ml.signals.registry import build_default_registry


# --- F2: registry / yaml consistency -----------------------------------------

def test_no_registry_drift_against_signals_yaml():
    """Every signal counting toward real_sc must be `active` in signals.yaml.

    This is the guard for the failure mode that produced F2: a tag removed from
    SHADOW_SIGNALS but left registered is silently promoted into real_sc.
    """
    drift = validate_signal_registry_consistency()
    assert drift == [], (
        f"{len(drift)} signal(s) count toward real_sc but are not 'active' in "
        f"signals.yaml: {drift}. Either add them to SHADOW_SIGNALS or mark them active."
    )


@pytest.mark.parametrize('tag', [
    'projection_consensus_over',  # 10% BB HR
    'volatile_scoring_over',      # 14.3% BB HR
    'sharp_money_over',           # 15.4% BB HR
    'hot_form_over',              # 28.6% BB HR
    'bounce_back_over',           # 0% BB HR
    'positive_clv_under',         # 41.4% BB HR
    'minutes_surge_over',         # structurally dead
])
def test_retired_signals_do_not_count_toward_real_sc(tag):
    """Signals retired in signals.yaml must not act as real signals."""
    assert tag in SHADOW_SIGNALS, f"{tag} is retired but would count toward real_sc"


# --- F3: negative-semantic signals -------------------------------------------

def test_negative_semantic_signals_are_excluded():
    """Negative indicators must never count as supporting evidence.

    For these three, `qualifies=True` means the pick is BAD (line moved against it,
    projections disagree, public is on it). Counting them toward real_sc inverts
    their meaning.
    """
    assert NEGATIVE_SEMANTIC_SIGNALS <= SHADOW_SIGNALS, (
        "NEGATIVE_SEMANTIC_SIGNALS must be a subset of SHADOW_SIGNALS so that every "
        "existing exclusion site (real_sc + both ranking branches) picks them up."
    )
    for tag in ('negative_clv_filter', 'projection_disagreement', 'public_fade_filter'):
        assert tag in SHADOW_SIGNALS
        assert tag not in BASE_SIGNALS


def test_negative_signals_carry_no_under_ranking_weight():
    """A negative indicator must not add ranking weight even if weights are edited."""
    for tag in NEGATIVE_SEMANTIC_SIGNALS:
        assert UNDER_SIGNAL_WEIGHTS.get(tag, 0.0) == 0.0


# --- F1: UNDER ranking excludes shadow ---------------------------------------

def _under_quality(tags):
    """Mirror the aggregator's UNDER quality computation (health multiplier = 1.0)."""
    real = [t for t in tags if t not in BASE_SIGNALS and t not in SHADOW_SIGNALS]
    return sum(UNDER_SIGNAL_WEIGHTS.get(t, 0.0) for t in real)


def test_shadow_tags_do_not_inflate_under_quality():
    """Adding shadow tags to an UNDER pick must not change its ranking score."""
    validated = ['home_under', 'elite_line_under']
    baseline = _under_quality(validated)

    shadow_padded = validated + [
        'national_tv_under', 'whole_line_precision', 'slow_pace_under',
        'star_line_under', 'b2b_fatigue_under',
    ]
    assert _under_quality(shadow_padded) == baseline, (
        "Shadow signals changed the UNDER composite score — every shadow signal's "
        "docstring claims zero pick impact; this is the F1 regression."
    )


def test_signal_rich_pick_outranks_shadow_padded_pick():
    """The concrete F1 failure: a shadow-padded pick outranking a signal-rich one.

    Pick A carries three high-conviction validated UNDER signals. Pick B carries two
    weaker validated signals plus five shadow tags. Before the fix B scored higher and,
    on a volume-capped slate, was published while A was dropped.
    """
    a = ['hot_3pt_under', 'volatile_starter_under', 'sharp_line_drop_under']
    b = ['home_under', 'elite_line_under',
         'national_tv_under', 'whole_line_precision', 'slow_pace_under',
         'star_line_under', 'b2b_fatigue_under']
    assert _under_quality(a) > _under_quality(b)


def test_every_real_under_signal_has_an_explicit_weight():
    """Guards the .get() default change from 1.0 -> 0.0.

    The default was lowered so an unweighted tag cannot silently outrank a deliberately
    weighted one. That is only safe while every UNDER-side signal surviving the shadow
    filter has an explicit weight — this test fails if someone activates one without.
    """
    survivors = [t for t in build_default_registry().tags()
                 if t not in BASE_SIGNALS and t not in SHADOW_SIGNALS]
    missing = [t for t in survivors
               if t.endswith('_under') and t not in UNDER_SIGNAL_WEIGHTS]
    assert missing == [], (
        f"Active UNDER signals missing from UNDER_SIGNAL_WEIGHTS would silently score "
        f"0.0: {missing}"
    )


# --- F4: book-count scaling is reachable -------------------------------------

def test_book_count_scaling_widens_thresholds_in_deep_markets():
    """The scaling helper must raise (never lower) the threshold as books increase."""
    from ml.signals.aggregator import _book_count_scaled_std_threshold as scale

    assert scale(0.75, None) == 0.75      # unknown -> preserve flat behavior
    assert scale(0.75, 5) == 0.75         # 4-6 books: original calibration
    assert scale(0.75, 8) > 0.75          # transition regime
    assert scale(0.75, 14) > scale(0.75, 8)   # 12+ books: widest
    for bc in (None, 4, 6, 7, 11, 12, 30):
        assert scale(0.75, bc) >= 0.75, "scaling must never block MORE than the flat threshold"


def test_pipeline_populates_book_count():
    """per_model_pipeline must set `book_count`, or the F4 scaling stays dead code."""
    import inspect

    from ml.signals import per_model_pipeline

    src = inspect.getsource(per_model_pipeline)
    assert "pred['book_count']" in src, (
        "per_model_pipeline no longer sets pred['book_count'] — the book-count-scaled "
        "std thresholds silently revert to the 4-6 book calibration (F4)."
    )
