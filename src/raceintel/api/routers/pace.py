from fastapi import APIRouter, HTTPException

from raceintel.api.schemas import PaceResponse
from raceintel.services.pace_service import get_pace

router = APIRouter(
    prefix="/pace",
    tags=["Pace"],
)


@router.get(
    "/{session_id}",
    response_model=list[PaceResponse],
)
def pace(session_id: int):
    result = get_pace(session_id)

    if not result:
        raise HTTPException(
            status_code=404,
            detail="Session not found",
        )

    return result