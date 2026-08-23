"""A BigQuery failure during grading is not "nothing to grade".

prediction_accuracy_processor caught NotFound / ServiceUnavailable /
DeadlineExceeded (and, in get_actuals_for_date, BadRequest) and returned [] or
{}. grade_date renders those as {'status': 'no_predictions'} and
{'status': 'no_actuals'} — success shapes, indistinguishable from a day with
genuinely nothing to grade.

The swallowing comment claimed it was "to allow Pub/Sub retry with backoff".
That never happened: the caller never saw an error, so nothing retried. The run
simply reported there was nothing to do.

Session 478 established this exact principle after a multi-column IN subquery
caused a six-day silent grading outage — but the fix was applied only to
BadRequest in get_predictions_for_date. get_actuals_for_date still swallowed
BadRequest specifically.

Re-raising costs nothing: an empty result grades zero rows either way. It only
changes whether anyone finds out.
"""

from datetime import date
from unittest.mock import Mock, patch

import pytest
from google.api_core import exceptions as gcp_exceptions
from google.cloud.exceptions import GoogleCloudError

from data_processors.grading.prediction_accuracy.prediction_accuracy_processor import (
    PredictionAccuracyProcessor,
)

INFRA_ERRORS = [
    pytest.param(gcp_exceptions.NotFound('gone'), id='NotFound'),
    pytest.param(gcp_exceptions.ServiceUnavailable('503'), id='ServiceUnavailable'),
    pytest.param(gcp_exceptions.DeadlineExceeded('timeout'), id='DeadlineExceeded'),
    pytest.param(GoogleCloudError('generic'), id='GoogleCloudError'),
]


@pytest.fixture
def processor():
    with patch(
        'data_processors.grading.prediction_accuracy.prediction_accuracy_processor.bigquery.Client'
    ):
        p = PredictionAccuracyProcessor()
    p.bq_client = Mock()
    return p


@pytest.mark.parametrize('error', INFRA_ERRORS)
def test_get_predictions_propagates_infra_errors(processor, error):
    processor.bq_client.query.side_effect = error
    with pytest.raises(type(error)):
        processor.get_predictions_for_date(date(2026, 3, 1))


@pytest.mark.parametrize('error', INFRA_ERRORS + [
    pytest.param(gcp_exceptions.BadRequest('bad sql'), id='BadRequest'),
])
def test_get_actuals_propagates_infra_errors(processor, error):
    """BadRequest included: Session 478's rule was never applied to this method."""
    processor.bq_client.query.side_effect = error
    with pytest.raises(type(error)):
        processor.get_actuals_for_date(date(2026, 3, 1))


def test_get_predictions_still_returns_empty_for_a_genuinely_empty_day(processor):
    """Guard against over-correcting: no data is not an error.

    If this ever fails, the gate has become a false alarm and every off-season
    day starts paging someone.
    """
    import pandas as pd
    processor.bq_client.query.return_value = Mock(to_dataframe=Mock(return_value=pd.DataFrame()))
    assert processor.get_predictions_for_date(date(2026, 8, 1)) == []


def test_get_actuals_still_returns_empty_for_a_genuinely_empty_day(processor):
    import pandas as pd
    processor.bq_client.query.return_value = Mock(to_dataframe=Mock(return_value=pd.DataFrame()))
    assert processor.get_actuals_for_date(date(2026, 8, 1)) == {}
