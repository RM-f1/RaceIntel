
from fastapi import APIRouter

from raceintel.chat.chat_service import ChatService
from raceintel.retrieval.retriever import RaceRetriever


router = APIRouter()

chat_service = ChatService()
retriever = RaceRetriever()


@router.post("/chat/")
def chat(request: dict):
    """
    Normal production chat endpoint.

    Flow:
        question -> ChatService -> Retriever -> Gemini -> answer
    """
    question = request["question"]

    answer = chat_service.ask(question)

    return {
        "answer": answer
    }


@router.post("/chat/evaluate")
def evaluate(request: dict):
    """
    Deterministic evaluation endpoint.

    IMPORTANT:
    This endpoint does NOT call Gemini.

    It only runs the retrieval layer and returns the
    structured documents retrieved from ChromaDB.
    """

    question = request["question"]

    results = retriever.retrieve(question)

    return {
        "question": question,
        "results": results,
    }
