"""ErrorContext must not change the exception passing through it.

It did, on every single error, in all 35 production files that use it.

`_log_error` built an `error_context` dict containing "error_type" and
"error_message", then called `log_error(error_type=..., error_message=...,
**error_context)`. Python raised:

    TypeError: log_error() got multiple values for keyword argument 'error_type'

raised from `__exit__` — so it REPLACED the exception being handled. Two
consequences, the second much worse than the first:

  1. Structured error logging never ran. The `log_error` call it exists for threw
     before emitting anything.
  2. `except <SpecificError>` anywhere downstream of an ErrorContext block could
     never match, because by then the exception was a TypeError.

(2) silently defeated real error handling. In
prediction_accuracy_processor.get_predictions_for_date, the Session 478 fix
re-raises BadRequest — added after a multi-column IN subquery caused a six-day
silent grading outage — but the query runs inside an ErrorContext, so BadRequest
had already become TypeError and fell through to `except Exception: return []`.
The fix for the outage was itself disabled by this bug.

Found 2026-08-23 while removing the grading swallow: taking away the `return []`
exposed the TypeError that the swallow had been absorbing.
"""

import pytest
from google.api_core import exceptions as gcp_exceptions

from shared.utils.error_context import ErrorContext


class Marker(Exception):
    """A type no error-handling machinery could plausibly special-case."""


@pytest.mark.parametrize('exc', [
    pytest.param(Marker('custom'), id='custom'),
    pytest.param(ValueError('bad value'), id='ValueError'),
    pytest.param(gcp_exceptions.BadRequest('bad sql'), id='BadRequest'),
    pytest.param(gcp_exceptions.NotFound('missing table'), id='NotFound'),
    pytest.param(gcp_exceptions.DeadlineExceeded('timeout'), id='DeadlineExceeded'),
])
def test_exception_type_survives(exc):
    with pytest.raises(type(exc)):
        with ErrorContext('some_operation', batch_id='b1'):
            raise exc


def test_exception_message_survives():
    with pytest.raises(ValueError, match='the real error'):
        with ErrorContext('some_operation'):
            raise ValueError('the real error')


def test_a_downstream_specific_handler_can_still_match():
    """The property that actually broke error handling in production."""
    matched = None
    try:
        with ErrorContext('grading_query', game_date='2026-03-01'):
            raise gcp_exceptions.BadRequest('multi-column IN subquery')
    except gcp_exceptions.BadRequest:
        matched = 'BadRequest'
    except Exception as e:
        matched = f'fell through to generic handler as {type(e).__name__}'
    assert matched == 'BadRequest', (
        f'specific handler did not match ({matched}); every `except <SpecificError>` '
        f'downstream of an ErrorContext is dead when this regresses'
    )


def test_the_rich_context_keys_are_still_passed_through():
    """The duplicate keys were stripped, not the whole context."""
    seen = {}
    import shared.utils.error_context as ec

    def fake_log_error(error_type, error_message, **extra):
        seen['error_type'] = error_type
        seen['error_message'] = error_message
        seen['extra'] = extra

    original = ec.log_error
    ec.log_error = fake_log_error
    try:
        with pytest.raises(ValueError):
            with ErrorContext('my_op', batch_id='b7', record_count=3):
                raise ValueError('boom')
    finally:
        ec.log_error = original

    assert seen['error_type'] == 'my_op_failed'
    assert seen['error_message'] == 'boom'
    assert seen['extra']['batch_id'] == 'b7'
    assert seen['extra']['record_count'] == 3
    assert seen['extra']['operation'] == 'my_op'
    # the stripped keys must not reappear as duplicates
    assert 'error_type' not in seen['extra']
    assert 'error_message' not in seen['extra']


def test_successful_blocks_are_unaffected():
    with ErrorContext('quiet_op'):
        result = 2 + 2
    assert result == 4
