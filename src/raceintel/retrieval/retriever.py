from raceintel.retrieval.chroma_client import ChromaClient


class Retriever:

    def __init__(self):
        self.client = ChromaClient()

    def retrieve(
        self,
        question: str,
        n_results: int = 5,
    ) -> str:

        question_lower = question.lower()

        race_keywords = [
            "winner",
            "won",
            "podium",
            "fastest lap",
            "race",
            "grand prix",
        ]

        if any(keyword in question_lower for keyword in race_keywords):
            where = {"source": "race_report"}
        else:
            where = {"source": "driver_summary"}

        results = self.client.collection.query(
            query_texts=[question],
            n_results=n_results,
            where=where,
        )

        documents = results.get("documents", [[]])[0]

        return "\n\n".join(documents)