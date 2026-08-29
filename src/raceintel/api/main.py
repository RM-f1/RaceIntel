from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from raceintel.api.routers import (
    health,
    sessions,
    drivers,
    constructors,
    races,
    weather,
    pace,
    standings,
    chat,
)

app = FastAPI(
    title="RaceIntel API",
    description="Formula 1 Analytics Backend",
    version="1.0.0",
)

# ---------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------

app.include_router(health.router)
app.include_router(sessions.router)
app.include_router(drivers.router)
app.include_router(constructors.router)
app.include_router(races.router)
app.include_router(weather.router)
app.include_router(pace.router)
app.include_router(standings.router)
app.include_router(chat.router)


# ---------------------------------------------------------------------
# Root endpoint
# ---------------------------------------------------------------------

@app.get("/")
def root():
    return {
        "message": "Welcome to RaceIntel API"
    }