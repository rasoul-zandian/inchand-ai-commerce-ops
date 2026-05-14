"""Provider-agnostic LLM surface (factory + types). Anthropic/Claude: future."""

from app.llm.factory import generate_text
from app.llm.types import LLMMessage, LLMResponse

__all__ = ["LLMMessage", "LLMResponse", "generate_text"]
