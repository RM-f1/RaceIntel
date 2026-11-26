from fastapi import APIRouter

from raceintel.api.schemas.chat import ChatRequest, ChatResponse
from raceintel.chat.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["Chat"])

_chat_service: ChatService | None = None


def get_chat_service() -> ChatService:
    """Lazily construct and cache the ChatService singleton on first use."""
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
    return _chat_service


@router.post("/", response_model=ChatResponse)
def chat(request: ChatRequest):
    answer = get_chat_service().ask(request.question)
    return ChatResponse(answer=answer)