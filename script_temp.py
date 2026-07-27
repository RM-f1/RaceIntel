from src.database.connection import SessionLocal
from src.database.models import (Constructor, Driver, Event, Lap, RaceResult,
                                 Season, Session, WeatherObservation)

db = SessionLocal()

print("Seasons:", db.query(Season).count())
print("Events:", db.query(Event).count())
print("Sessions:", db.query(Session).count())
print("Constructors:", db.query(Constructor).count())
print("Drivers:", db.query(Driver).count())
print("Race Results:", db.query(RaceResult).count())
print("Laps:", db.query(Lap).count())
print("Weather:", db.query(WeatherObservation).count())
