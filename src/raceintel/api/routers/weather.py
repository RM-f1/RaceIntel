from fastapi import APIRouter, HTTPException

from raceintel.api.schemas import WeatherResponse
from raceintel.services.weather_service import get_weather

router = APIRouter(
    prefix="/weather",
    tags=["Weather"],
)


@router.get(
    "/{session_id}",
    response_model=WeatherResponse,
)
def weather(session_id: int):
    result = get_weather(session_id)

    if not result:
        raise HTTPException(
            status_code=404,
            detail="Session not found",
        )

    return result