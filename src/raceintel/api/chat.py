from fastapi import APIRouter

from raceintel.chat.chat_service import ChatService
from raceintel.chat.schemas import ChatQueryRequest

router = APIRouter(
    prefix="/chat",
    tags=["Chat"],
)

chat_service = ChatService()


@router.post("/query")
def query(request: ChatQueryRequest):
    
    return chat_service.retrieve_context(
        request.question
    )