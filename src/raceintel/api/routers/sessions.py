from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from raceintel.api.dependencies import get_db
from raceintel.api.schemas import SessionResponse
from raceintel.services.session_service import get_sessions

router = APIRouter(
    prefix="/sessions",
    tags=["Sessions"],
)


@router.get(
    "/",
    response_model=list[SessionResponse],
)
def list_sessions(
    season: int | None = None,
    db: Session = Depends(get_db),
):
    sessions = get_sessions(
        db=db,
        season=season,
    )

    return [
        SessionResponse(
            session_id=session.session_id,
            season=session.event.season.season_year,
            event_name=session.event.event_name,
            session_type=session.session_type,
            session_name=session.session_name,
        )
        for session in sessions
    ]