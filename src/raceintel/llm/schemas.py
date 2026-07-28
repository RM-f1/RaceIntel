from pydantic import BaseModel


class LLMResponse(BaseModel):
    answer: str
    confidence: float