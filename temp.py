from sqlalchemy import text
from src.database.connection import SessionLocal

with SessionLocal() as session:
    result = session.execute(text("""
        SELECT
            COUNT(*)
        FROM laps
        WHERE is_personal_best = 1;
    """))

    print(result.scalar())