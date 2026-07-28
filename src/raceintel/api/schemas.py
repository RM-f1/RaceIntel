from pydantic import BaseModel


class SessionResponse(BaseModel):
    session_id: int
    season: int
    event_name: str
    session_type: str
    session_name: str

    model_config = {
        "from_attributes": True
    }

class DriverResponse(BaseModel):
    driver_id: int
    driver_code: str
    driver_number: int | None
    driver_full_name: str
    constructor: str |None

    model_config = {
        "from_attributes": True
    }

class ConstructorResponse(BaseModel):
    constructor_id: int
    constructor_name: str

    model_config = {
        "from_attributes": True
    }
class BiggestMoverResponse(BaseModel):
    driver: str
    positions: int


class FastestLapResponse(BaseModel):
    driver: str
    seconds: float


class RaceStatisticsResponse(BaseModel):
    drivers: int
    constructors: int
    weather_samples: int


class RaceReportResponse(BaseModel):
    session_id: int
    winner: str
    podium: list[str]
    top_constructor: str
    biggest_mover: BiggestMoverResponse
    fastest_lap: FastestLapResponse
    statistics: RaceStatisticsResponse

class BiggestMoverResponse(BaseModel):
    driver: str
    positions: int


class FastestLapResponse(BaseModel):
    driver: str
    seconds: float


class RaceStatisticsResponse(BaseModel):
    drivers: int
    constructors: int
    weather_samples: int
    tyre_compounds: list[str]


class RaceReportResponse(BaseModel):
    session_id: int
    winner: str
    podium: list[str]
    top_constructor: str
    biggest_mover: BiggestMoverResponse
    fastest_lap: FastestLapResponse
    statistics: RaceStatisticsResponse

class WeatherResponse(BaseModel):
    average_air_temperature: float
    average_track_temperature: float
    average_humidity: float
    average_wind_speed: float
    average_pressure: float

class PaceResponse(BaseModel):
    driver_code: str
    driver_full_name: str
    fastest_lap_seconds: float

class DriverStandingResponse(BaseModel):
    finish_position: int
    driver_code: str
    driver_full_name: str
    constructor_name: str
    points_scored: float

class ConstructorStandingResponse(BaseModel):
    constructor_name: str
    total_points: float