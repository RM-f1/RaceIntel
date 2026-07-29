from raceintel.knowledge.knowledge_service import KnowledgeService
from raceintel.llm.llm_service import LLMService


class ChatService:

    def __init__(self):
        self.knowledge = KnowledgeService()
        self.llm = LLMService()

    def ask(self, question: str) -> str:
        

        context = self.knowledge.get_context(question)

        print("\n========== CONTEXT SENT TO LLM ==========\n")
        print(context)
        print("\n=========================================\n")


        response = self.llm.generate(
            question=question,
            context=context,
        )

        return response.answer