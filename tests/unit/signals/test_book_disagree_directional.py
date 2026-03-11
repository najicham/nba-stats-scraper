"""Tests for direction-specific book disagreement signals.

Session 469: Split book_disagreement into book_disagree_over and book_disagree_under.
"""

import pytest
from ml.signals.book_disagree_over import BookDisagreeOverSignal
from ml.signals.book_disagree_under import BookDisagreeUnderSignal


class TestBookDisagreeOver:
    """Tests for BookDisagreeOverSignal."""

    def setup_method(self):
        self.signal = BookDisagreeOverSignal()

    def test_tag(self):
        assert self.signal.tag == "book_disagree_over"

    def test_qualifies_over_high_std(self):
        pred = {'recommendation': 'OVER', 'player_lookup': 'test', 'game_id': 'g1'}
        supp = {'book_stats': {'multi_book_line_std': 2.0, 'book_count': 8}}
        result = self.signal.evaluate(pred, supplemental=supp)
        assert result.qualifies is True
        assert result.source_tag == "book_disagree_over"
        assert result.metadata['backtest_hr'] == 79.6

    def test_rejects_under_direction(self):
        pred = {'recommendation': 'UNDER', 'player_lookup': 'test', 'game_id': 'g1'}
        supp = {'book_stats': {'multi_book_line_std': 2.0, 'book_count': 8}}
        result = self.signal.evaluate(pred, supplemental=supp)
        assert result.qualifies is False

    def test_rejects_low_std(self):
        pred = {'recommendation': 'OVER', 'player_lookup': 'test', 'game_id': 'g1'}
        supp = {'book_stats': {'multi_book_line_std': 1.0, 'book_count': 8}}
        result = self.signal.evaluate(pred, supplemental=supp)
        assert result.qualifies is False

    def test_rejects_few_books(self):
        pred = {'recommendation': 'OVER', 'player_lookup': 'test', 'game_id': 'g1'}
        supp = {'book_stats': {'multi_book_line_std': 2.0, 'book_count': 3}}
        result = self.signal.evaluate(pred, supplemental=supp)
        assert result.qualifies is False

    def test_fallback_prediction_dict(self):
        pred = {
            'recommendation': 'OVER', 'player_lookup': 'test', 'game_id': 'g1',
            'multi_book_line_std': 1.8, 'book_count': 7,
        }
        result = self.signal.evaluate(pred)
        assert result.qualifies is True

    def test_no_supplemental_data(self):
        pred = {'recommendation': 'OVER', 'player_lookup': 'test', 'game_id': 'g1'}
        result = self.signal.evaluate(pred)
        assert result.qualifies is False


class TestBookDisagreeUnder:
    """Tests for BookDisagreeUnderSignal."""

    def setup_method(self):
        self.signal = BookDisagreeUnderSignal()

    def test_tag(self):
        assert self.signal.tag == "book_disagree_under"

    def test_qualifies_under_high_std(self):
        pred = {'recommendation': 'UNDER', 'player_lookup': 'test', 'game_id': 'g1'}
        supp = {'book_stats': {'multi_book_line_std': 2.0, 'book_count': 8}}
        result = self.signal.evaluate(pred, supplemental=supp)
        assert result.qualifies is True
        assert result.source_tag == "book_disagree_under"

    def test_rejects_over_direction(self):
        pred = {'recommendation': 'OVER', 'player_lookup': 'test', 'game_id': 'g1'}
        supp = {'book_stats': {'multi_book_line_std': 2.0, 'book_count': 8}}
        result = self.signal.evaluate(pred, supplemental=supp)
        assert result.qualifies is False

    def test_rejects_low_std(self):
        pred = {'recommendation': 'UNDER', 'player_lookup': 'test', 'game_id': 'g1'}
        supp = {'book_stats': {'multi_book_line_std': 1.2, 'book_count': 8}}
        result = self.signal.evaluate(pred, supplemental=supp)
        assert result.qualifies is False
