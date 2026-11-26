import shutil
from datetime import datetime

from sqlalchemy import text

from database.connection import DATABASE_PATH, engine

EXPECTED = 334

backup = DATABASE_PATH.with_name(f"raceintel_backup_{datetime.now():%Y%m%d_%H%M%S}.db")
shutil.copy2(DATABASE_PATH, backup)
print(f"Backup written: {backup}")

with engine.begin() as conn:
    n = conn.execute(text("SELECT COUNT(*) FROM laps WHERE tyre_compound = 'None'")).scalar()
    print(f"Rows with the string 'None': {n}")
    if n != EXPECTED:
        raise SystemExit(f"Expected {EXPECTED}, found {n}. Nothing changed.")
    nulls_before = conn.execute(text("SELECT COUNT(*) FROM laps WHERE tyre_compound IS NULL")).scalar()
    res = conn.execute(text("UPDATE laps SET tyre_compound = NULL WHERE tyre_compound = 'None'"))
    print(f"Updated {res.rowcount} rows")
    left = conn.execute(text("SELECT COUNT(*) FROM laps WHERE tyre_compound = 'None'")).scalar()
    nulls_after = conn.execute(text("SELECT COUNT(*) FROM laps WHERE tyre_compound IS NULL")).scalar()
    if left != 0 or nulls_after != nulls_before + EXPECTED:
        raise RuntimeError("Verification failed, rolling back.")
    print(f"NULL compounds: {nulls_before} -> {nulls_after}. Committing.")