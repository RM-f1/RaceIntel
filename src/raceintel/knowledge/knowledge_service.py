from raceintel.retrieval.retriever import Retriever


class KnowledgeService:

    def __init__(self):
        self.retriever = Retriever()

    def get_context(self, question: str) -> str:
        return self.retriever.retrieve(question)

    def search(self, query: str) -> dict:
        return {
            "query": query,
            "context": self.retriever.retrieve(query),
        }