"""
Guards the C3 pre-registered two-tier promotion gates (measurement-infra 2026-07).

These assertions lock the structure of the `promotion:` blocks and the
stream_block_class classification so they cannot silently drift away from
PREREG-promotion-gates-2026-27.md. Threshold VALUES are intentionally frozen in
the YAML/doc (the git history is the pre-registration record); this test checks
the machine-readable contract the C4 tracker depends on.
"""

from pathlib import Path

import pytest
import yaml

REGISTRY = Path(__file__).resolve().parents[3] / 'shared' / 'registry'

GATED_SIGNALS = {
    'line_converging_under', 'whole_line_precision',
    'b2b_fatigue_under', 'national_tv_under',
}
GATED_FILTERS = {'low_variance_under_block', 'clv_diverge_under_block'}


@pytest.fixture(scope='module')
def signals():
    return yaml.safe_load((REGISTRY / 'signals.yaml').read_text())['signals']


@pytest.fixture(scope='module')
def filters_doc():
    return yaml.safe_load((REGISTRY / 'filters.yaml').read_text())


def _by_tag(entries):
    return {e['tag']: e for e in entries}


def test_gated_signals_have_promotion_blocks(signals):
    by_tag = _by_tag(signals)
    for tag in GATED_SIGNALS:
        assert tag in by_tag, f"gated signal {tag} missing from registry"
        promo = by_tag[tag].get('promotion')
        assert promo, f"{tag} has no promotion block"
        assert promo['prereg_doc'] == 'PREREG-promotion-gates-2026-27.md'
        assert promo['prereg_date'] == '2026-07-04'
        # OVER promotion is frozen — every gated signal must say so.
        assert 'over_promotion' in promo.get('cannot_license', [])


def test_gated_filters_have_promotion_blocks(filters_doc):
    by_tag = _by_tag(filters_doc['filters'])
    for tag in GATED_FILTERS:
        assert tag in by_tag, f"gated filter {tag} missing from registry"
        promo = by_tag[tag].get('promotion')
        assert promo and promo['kind'] == 'filter_cf_hr'
        assert promo['prereg_doc'] == 'PREREG-promotion-gates-2026-27.md'
        # Filter gates are Class B (outcome-correlated) and must say so.
        assert by_tag[tag].get('block_class') == 'B'


def test_line_converging_is_data_gated(signals):
    promo = _by_tag(signals)['line_converging_under']['promotion']
    assert 'phase6-clv-reexport' in promo['data_gated_on']


def test_national_tv_unresolvable_this_season(signals):
    promo = _by_tag(signals)['national_tv_under']['promotion']
    assert promo['resolvable_this_season'] is False


def test_stream_block_class_default_is_b(filters_doc):
    assert filters_doc['stream_block_class']['default'] == 'B'


def test_class_a_tags_are_known_active_filters(filters_doc):
    by_tag = _by_tag(filters_doc['filters'])
    for tag in filters_doc['stream_block_class']['class_a']:
        assert tag in by_tag, f"Class-A tag {tag} is not a known filter"
        assert by_tag[tag]['status'] != 'removed', f"Class-A tag {tag} is removed"


def test_no_gated_filter_is_class_a(filters_doc):
    """The two gated filters are outcome-correlated — they must NOT leak into the
    Tier-1 (Class-A) population that measures the signals."""
    class_a = set(filters_doc['stream_block_class']['class_a'])
    assert GATED_FILTERS.isdisjoint(class_a)
