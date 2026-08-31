"""An ungraded prediction is not a loss.

`model_performance.py` builds hit rates with
`CASE WHEN prediction_correct THEN 1 ELSE 0 END`. In BigQuery that maps NULL to
0, so a not-yet-graded row counts against the model. The `daily_results` CTE was
missing the `prediction_correct IS NOT NULL` filter that every other CTE in the
same query already had.

Measured on `prediction_accuracy` before the fix:

  window                 ungraded   HR as computed   true graded HR
  2026-01-01..04-07        25.6%         39.6%           53.2%
  2026-02-22..03-01        35.4%         34.1%           52.8%

13.6 and 18.7 points of understatement. The decay thresholds are BLOCKED < 52.4,
DEGRADING < 55, WATCH < 58, and `decay_detection` AUTO-DISABLES BLOCKED models,
so this silently pushed healthy models toward being switched off — and it did so
hardest exactly when grading lagged, i.e. when the pipeline was already unwell.

Per-model over the 7 days to 2026-03-01, two of twelve models were BLOCKED purely
because of this. `ensemble_v1` read **8.3%** and was really **62.5%** — the best
model in the fleet, one auto-disable away from being turned off.

These tests are structural. The metric is computed in a SQL string against a
table these tests cannot reach, so they assert the shape of the query: any CTE
that turns `prediction_correct` into a win/loss must also exclude ungraded rows.
"""

import re

import pytest

from ml.analysis import model_performance


def _query_text():
    """The SQL built by compute_for_date, without touching BigQuery.

    The query is a module-level string literal inside the function, so it is
    recovered from the source rather than by executing anything.
    """
    import inspect
    return inspect.getsource(model_performance.compute_for_date)


def _strip_sql_comments(sql: str) -> str:
    """Drop `--` comment tails.

    Without this, these tests match prose. The first version failed because the
    explanatory comments above the CTE quote the very `>= 3` filter they are
    describing — the same comment-matching trap that made an earlier guard in
    this repo reach a correct verdict for the wrong reason.
    """
    out = []
    for line in sql.splitlines():
        i = line.find('--')
        out.append(line if i == -1 else line[:i])
    return '\n'.join(out)


def _ctes(sql: str):
    """Yield (name, body) for each `name AS ( ... )` CTE, brace-matched.

    Comments are stripped first so assertions test SQL, not prose.
    """
    sql = _strip_sql_comments(sql)
    for m in re.finditer(r'(\w+)\s+AS\s*\(', sql):
        name = m.group(1)
        i, depth = m.end(), 1
        while i < len(sql) and depth:
            if sql[i] == '(':
                depth += 1
            elif sql[i] == ')':
                depth -= 1
            i += 1
        yield name, sql[m.end():i]


_UNCOND_ALIASES = [
    'pred_bias_uncond_7d', 'pred_bias_uncond_14d', 'pred_bias_uncond_n_7d',
    'pred_bias_uncond_t_7d', 'cover_margin_7d', 'cover_margin_t_7d',
    'realization_beta_14d',
]


def _expr_for(body: str, alias: str) -> str:
    """The SQL expression assigned to `AS <alias>`, and only that expression.

    In SQL the alias trails its expression, so naive slicing up to the alias name
    swallows the preceding expressions too — which is how the first version of
    these tests read cover_margin's edge filter as though it belonged to the
    unconditional bias. Bound each expression by the previous alias instead.
    """
    end = body.index('AS ' + alias)
    idx = _UNCOND_ALIASES.index(alias)
    start = 0
    if idx > 0:
        prev = 'AS ' + _UNCOND_ALIASES[idx - 1]
        if prev in body:
            start = body.index(prev) + len(prev)
    return body[start:end]


class TestUngradedIsNotALoss:

    def test_the_parser_finds_the_ctes(self):
        """Guard the guard: a broken regex would make everything below vacuous."""
        names = [n for n, _ in _ctes(_query_text())]
        assert 'daily_results' in names, f'daily_results not parsed; found {names}'
        assert len(names) >= 4, f'expected several CTEs, found {names}'

    def test_daily_results_excludes_ungraded_rows(self):
        """The specific regression: this CTE feeds rolling_hr_* and the state machine."""
        body = dict(_ctes(_query_text()))['daily_results']
        assert 'prediction_correct IS NOT NULL' in body, (
            'daily_results must exclude ungraded rows — without it, '
            'CASE WHEN prediction_correct THEN 1 ELSE 0 END counts every '
            'ungraded prediction as a loss and drives models to BLOCKED'
        )

    def test_every_win_computing_cte_excludes_ungraded_rows(self):
        """The general rule, so a new CTE cannot reintroduce the bug.

        Any CTE that collapses `prediction_correct` into a number is computing a
        win/loss and must first exclude ungraded rows. Deliberately no allowlist.
        """
        offenders = []
        for name, body in _ctes(_query_text()):
            computes_win = re.search(
                r'(CASE\s+WHEN\s+prediction_correct|COUNTIF\s*\(\s*prediction_correct\s*\))',
                body,
            )
            if computes_win and 'prediction_correct IS NOT NULL' not in body:
                offenders.append(name)
        assert not offenders, (
            'these CTEs turn prediction_correct into a win/loss without excluding '
            f'ungraded rows, so NULL counts as a loss: {offenders}'
        )


class TestUnconditionalDiagnostics:
    """The drift columns must not inherit the edge>=3 selection."""

    def test_uncond_cte_exists(self):
        assert 'uncond_stats' in dict(_ctes(_query_text()))

    def test_unconditional_bias_is_not_edge_filtered(self):
        """The whole point: bias measured on rows the model did NOT select.

        bias_stats conditions on ABS(predicted - line) >= 3, a subsample the
        model chooses for itself. Measured 2026-01-01..04-07 that subsample reads
        -2.236 against -0.978 unconditionally; most of the 2.3x gap is selection,
        because conditioning on |predicted - line| picks extreme predictions and
        extreme predictions regress.
        """
        body = dict(_ctes(_query_text()))['uncond_stats']
        bias_expr = _expr_for(body, 'pred_bias_uncond_7d')
        assert 'predicted_points - actual_points' in bias_expr
        assert '>= 3' not in bias_expr, (
            'the unconditional bias must not be edge-filtered — that is the '
            'selection effect it exists to remove'
        )

    def test_realization_beta_uses_the_full_edge_range(self):
        """Restricting the range attenuates the slope toward zero.

        beta -> 0 is precisely the "confidently wrong" reading, so computing it on
        a restricted range would manufacture the signal it is meant to detect.
        """
        body = dict(_ctes(_query_text()))['uncond_stats']
        beta_expr = _expr_for(body, 'realization_beta_14d')
        assert 'COVAR_SAMP' in beta_expr and 'VAR_SAMP' in beta_expr
        assert '>= 3' not in beta_expr, (
            'range restriction attenuates beta toward zero, faking staleness'
        )

    def test_cover_margin_stays_comparable_to_hit_rate(self):
        """Negative test: cover margin SHOULD keep the edge filter.

        It is the magnitude behind rolling_hr_*, so it must be measured on the
        same population or the two cannot be read together.
        """
        body = dict(_ctes(_query_text()))['uncond_stats']
        cm = _expr_for(body, 'cover_margin_7d')
        assert '>= 3' in cm, (
            'cover_margin must stay on edge>=3 so it is comparable with rolling_hr_*'
        )
