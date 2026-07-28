from fastapi import APIRouter, HTTPException

from raceintel.api.schemas import RaceReportResponse
from raceintel.services.race_service import get_race_report

router = APIRouter(
    prefix="/races",
    tags=["Race Report"],
)


@router.get(
    "/{session_id}",
    response_model=RaceReportResponse,
)
def race_report(session_id: int):
    try:
        return get_race_report(session_id)

    except IndexError:
        raise HTTPException(
            status_code=404,
            detail="Session not found",
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )