from fastapi import APIRouter, HTTPException

from raceintel.api.schemas import (
    DriverStandingResponse,
    ConstructorStandingResponse,
)

from raceintel.services.standings_service import (
    get_driver_championship,
    get_constructor_championship,
)

router = APIRouter(
    prefix="/standings",
    tags=["Standings"],
)


@router.get(
    "/drivers/{session_id}",
    response_model=list[DriverStandingResponse],
)
def driver_standings(session_id: int):
    result = get_driver_championship(session_id)

    if not result:
        raise HTTPException(
            status_code=404,
            detail="Session not found",
        )

    return result

@router.get(
    "/constructors/{session_id}",
    response_model=list[ConstructorStandingResponse],
)
def constructor_standings(session_id: int):
    result = get_constructor_championship(session_id)

    if not result:
        raise HTTPException(
            status_code=404,
            detail="Session not found",
        )

    return result

