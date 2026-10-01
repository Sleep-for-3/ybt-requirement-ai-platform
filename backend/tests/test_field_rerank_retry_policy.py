"""Guards for the anti-empty ranking policy and the bounded retry constants introduced on 2026-10-01."""
from app.services.ai_skills import field_rerank, runtime


def test_field_rerank_prompt_forbids_an_empty_ranking():
    prompt = runtime.FIELD_RERANK_SAFETY_PROMPT
    assert "An empty ranking is invalid output" in prompt
    assert "still return it exactly once" in prompt


def test_bounded_retry_is_limited_and_targets_only_the_observed_failure():
    assert field_rerank.MAX_RERANK_ATTEMPTS == 2, "the retry must stay bounded to a single extra attempt"
    assert field_rerank.RETRYABLE_MODEL_FAILURES == {"invalid_model_response"}, (
        "only an explicitly invalid model response may be retried; outages and policy denials must not"
    )