from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from raceintel.api.dependencies import get_db
from raceintel.api.schemas import ConstructorResponse
from raceintel.services.constructor_service import get_constructors

router = APIRouter(
    prefix="/constructors",
    tags=["Constructors"],
)


@router.get(
    "/",
    response_model=list[ConstructorResponse],
)
def list_constructors(
    db: Session = Depends(get_db),
):
    constructors = get_constructors(db)

    return [
        ConstructorResponse(
            constructor_id=constructor.constructor_id,
            constructor_name=constructor.constructor_name,
        )
        for constructor in constructors
    ]