from pathlib import Path

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.utils.embedding_functions import (
    SentenceTransformerEmbeddingFunction,
)

from raceintel.retrieval.schemas import RaceDocument


class ChromaClient:
   

    def __init__(self, persist_directory: str = "data/chroma"):
        db_path = Path(persist_directory)

        self.client = chromadb.PersistentClient(
            path=str(db_path)
        )

        self.collection: Collection = self.client.get_or_create_collection(
            name="raceintel_knowledge"
        )

    def add_document(self, document: RaceDocument) -> None:
        

        self.collection.add(
            ids=[document.id],
            documents=[document.text],
            metadatas=[document.metadata],
        )

    def add_documents(
        self,
        documents: list[RaceDocument],
    ) -> None:
       

        self.collection.add(
            ids=[doc.id for doc in documents],
            documents=[doc.text for doc in documents],
            metadatas=[doc.metadata for doc in documents],
        )

    def count(self) -> int:
       

        return self.collection.count()

    def reset_collection(self) -> None:
   

    self.client.delete_collection("raceintel_knowledge")

    embedding_function = SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )

    self.collection = self.client.get_or_create_collection(
        name="raceintel_knowledge",
        embedding_function=embedding_function,
    )