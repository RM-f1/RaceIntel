import os
from pathlib import Path
from typing import Any

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings, Space

from raceintel.retrieval.schemas import RaceDocument


class LazySentenceTransformerEmbeddingFunction(EmbeddingFunction[Documents]):
    """ChromaDB embedding function that defers loading SentenceTransformer until first use."""

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        device: str = "cpu",
        normalize_embeddings: bool = False,
        **kwargs: Any,
    ):
        self.model_name = model_name
        self.device = device
        self.normalize_embeddings = normalize_embeddings
        self.kwargs = kwargs
        self._fn: Any = None

    def _get_fn(self) -> Any:
        if self._fn is None:
            from chromadb.utils.embedding_functions import (
                SentenceTransformerEmbeddingFunction,
            )

            self._fn = SentenceTransformerEmbeddingFunction(
                model_name=self.model_name,
                device=self.device,
                normalize_embeddings=self.normalize_embeddings,
                **self.kwargs,
            )
        return self._fn

    def __call__(self, input: Documents) -> Embeddings:
        return self._get_fn()(input)

    def embed_query(self, input: Documents) -> Embeddings:
        return self._get_fn().embed_query(input)

    @staticmethod
    def name() -> str:
        return "sentence_transformer"

    def default_space(self) -> Space:
        return "cosine"

    def supported_spaces(self) -> list[Space]:
        return ["cosine", "l2", "ip"]

    def get_config(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "device": self.device,
            "normalize_embeddings": self.normalize_embeddings,
            "kwargs": self.kwargs,
        }

    @staticmethod
    def build_from_config(
        config: dict[str, Any],
    ) -> "LazySentenceTransformerEmbeddingFunction":
        return LazySentenceTransformerEmbeddingFunction(
            model_name=config.get("model_name", "all-MiniLM-L6-v2"),
            device=config.get("device", "cpu"),
            normalize_embeddings=config.get("normalize_embeddings", False),
            **config.get("kwargs", {}),
        )

    def validate_config_update(
        self, old_config: dict[str, Any], new_config: dict[str, Any]
    ) -> None:
        return


class ChromaClient:
    

    def __init__(
        self,
        persist_directory: str = "data/chroma",
        embedding_function=None,
    ):
        db_path = Path(persist_directory)

        self.client = chromadb.PersistentClient(
            path=str(db_path)
        )

        if embedding_function is None:
            embedding_function = LazySentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )

        self.embedding_function = embedding_function

        self.collection: Collection = self.client.get_or_create_collection(
            name="raceintel_knowledge",
            embedding_function=embedding_function,
        )

    def add_document(self, document: RaceDocument) -> None:
        self.collection.upsert(
            ids=[document.id],
            documents=[document.text],
            metadatas=[document.metadata],
        )

    def add_documents(
        self,
        documents: list[RaceDocument],
    ) -> None:
        self.collection.upsert(
            ids=[doc.id for doc in documents],
            documents=[doc.text for doc in documents],
            metadatas=[doc.metadata for doc in documents],
        )

    def count(self) -> int:
        return self.collection.count()

    def reset_collection(self) -> None:
        self.client.delete_collection("raceintel_knowledge")

        self.collection = self.client.get_or_create_collection(
            name="raceintel_knowledge",
            embedding_function=self.embedding_function,
        )