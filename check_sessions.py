from src.database.connection import SessionLocal, engine

print("Database:", engine.url)

db = SessionLocal()
from src.database.models import Session

db = SessionLocal()

sessions = db.query(Session).all()

for s in sessions:
    print(
        s.session_id,
        s.event_id,
        s.session_type,
        s.session_name,
    )

db.close()
