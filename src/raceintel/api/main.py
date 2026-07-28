from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from raceintel.api.chat import router as chat_router

from raceintel.api.routers import (
    health,
    sessions,
    drivers,
    constructors,
    races,
    weather,
    pace,
    standings,
)

app = FastAPI(
    title="RaceIntel API",
    description="Formula 1 Analytics Backend",
    version="1.0.0",
)

# Allow frontend applications (e.g. Streamlit) to access the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # For development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(sessions.router)
app.include_router(drivers.router)
app.include_router(constructors.router)
app.include_router(races.router)
app.include_router(weather.router)
app.include_router(pace.router)
app.include_router(standings.router)
app.include_router(chat_router)


@app.get("/")
def root():
    return {
        "message": "Welcome to RaceIntel API"
    }