
from google import genai
from google.genai import errors

from raceintel.config import settings


class GeminiClient:

    def __init__(self):
        self.client = genai.Client(
            api_key=settings.GEMINI_API_KEY
        )

    def generate(self, prompt: str) -> str:
        try:
            response = self.client.models.generate_content(
                model="gemini-3.5-flash",
                contents=prompt,
                config={
                    "temperature": 0.0,
                },
            )

            return response.text

        except errors.ClientError as e:
            if e.code == 429:
                return (
                    "Gemini API quota exceeded. "
                    "Please try again later."
                )

            raise
