from app.services.llm.base import LLMService


def get_llm_service(*args, **kwargs):
    from app.services.llm.factory import get_llm_service as factory

    return factory(*args, **kwargs)

__all__ = ["LLMService", "get_llm_service"]
