from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from raceintel.api.dependencies import get_db

router = APIRouter(
    prefix="/health",
    tags=["Health"],
)


def _check_sqlite_file(db: Session) -> None:
    """Verify the target SQLite file exists and is non-empty before querying."""
    bind = db.get_bind()
    db_file = getattr(getattr(bind, "url", None), "database", None)
    if db_file and db_file != ":memory:":
        path = Path(db_file)
        if not path.is_file() or path.stat().st_size == 0:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Database unavailable at '{path}'. "
                    "Set RACEINTEL_DB_PATH to a valid SQLite database or build data/raceintel.db."
                ),
            )


@router.get("/")
def health_check(db: Session = Depends(get_db)):
    _check_sqlite_file(db)
    try:
        db.execute(text("SELECT 1 FROM seasons LIMIT 1"))
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Database schema check failed: {exc}",
        )

    return {
        "status": "healthy",
        "database": "connected",
    }