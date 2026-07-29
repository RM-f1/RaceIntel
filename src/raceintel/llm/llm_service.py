from ollama import chat

from raceintel.llm.prompts import SYSTEM_PROMPT
from raceintel.llm.schemas import AIResponse


class LLMService:
    def __init__(self, model: str = "qwen2.5:3b"):
        self.model = model

    def generate(
        self,
        question: str,
        context: str,
    ) -> AIResponse:

        response = chat(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": f"""
Context:
{context}

Question:
{question}
""",
                },
            ],
        )

        return AIResponse(
            answer=response.message.content
        )