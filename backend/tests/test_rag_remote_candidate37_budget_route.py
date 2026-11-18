import pytest

from rag_remote_candidate37_budget_route import validate_zero_candidate_budget


def summary(**changes):
    result = {
        'scope': 'candidate37-test',
        'max_new_provider_requests': 0,
        'max_new_total_tokens': 0,
        'provider_requests_used': 0,
        'provider_requests_reserved': 0,
        'total_tokens_used': 0,
        'total_tokens_reserved': 0,
        'unknown_usage_requests': 0,
    }
    result.update(changes)
    return result


def test_zero_budget_accepts_uninitialized_limits_with_no_attempts():
    validate_zero_candidate_budget(summary(), None, 0)


def test_zero_budget_accepts_initialized_zero_limits():
    validate_zero_candidate_budget(summary(), ('candidate37-test', 0, 0), 0)


@pytest.mark.parametrize(('limits_row', 'attempt_count'), [
    (('candidate37-test', 1, 10000), 0),
    (('candidate37-test', 0, 0), 1),
])
def test_zero_budget_rejects_nonzero_limit_or_any_attempt(limits_row, attempt_count):
    with pytest.raises(RuntimeError):
        validate_zero_candidate_budget(summary(), limits_row, attempt_count)


def test_zero_budget_rejects_summary_reservation():
    with pytest.raises(RuntimeError):
        validate_zero_candidate_budget(summary(provider_requests_reserved=1), None, 0)
