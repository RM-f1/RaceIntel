from fastapi import APIRouter

from raceintel.api.schemas import ChatRequest, ChatResponse
from raceintel.chat.chat_service import ChatService

router = APIRouter(
    prefix="/chat",
    tags=["AI"],
)

chat_service = ChatService()


@router.post(
    "",
    response_model=ChatResponse,
)
def ask_chat(request: ChatRequest):

    answer = chat_service.ask(request.question)

    return ChatResponse(
        answer=answer,
    )