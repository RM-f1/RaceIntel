from raceintel.knowledge.knowledge_service import KnowledgeService


class ChatService:
   
    def __init__(self):
        self.knowledge = KnowledgeService()

    def retrieve_context(
        self,
        question: str,
    ) -> dict:
       

        return self.knowledge.search(question)