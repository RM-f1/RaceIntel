from raceintel.retrieval.chroma_client import ChromaClient


class Retriever:
   

    def __init__(self):
        self.client = ChromaClient()

    def search(
        self,
        query: str,
        n_results: int = 5,
    ) -> dict:
        

        return self.client.collection.query(
            query_texts=[query],
            n_results=n_results,
        )

    def search_by_metadata(
        self,
        query: str,
        metadata_filter: dict[str,Any],
        n_results: int = 5,
    ) -> dict:
       

        return self.client.collection.query(
            query_texts=[query],
            where=metadata_filter,
            n_results=n_results,
        )