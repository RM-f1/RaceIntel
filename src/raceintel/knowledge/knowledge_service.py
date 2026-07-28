from raceintel.retrieval.retriever import Retriever


class KnowledgeService:
   
    def __init__(self):
        self.retriever = Retriever()

    def search(
        self,
        query: str,
        n_results: int = 5,
    ) -> dict:
        
        return self.retriever.search(
            query=query,
            n_results=n_results,
        )