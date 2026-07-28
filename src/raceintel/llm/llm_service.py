from raceintel.llm.schemas import LLMResponse


class LLMService:
    
    def generate(
        self,
        question: str,
        context: str,
    ) -> LLMResponse:

        return LLMResponse(
            answer="LLM integration coming in Sprint 2.",
            confidence=0.0,
        )