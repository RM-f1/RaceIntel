from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from raceintel.api.dependencies import get_db
from raceintel.api.schemas import DriverResponse
from raceintel.services.driver_service import get_drivers

router = APIRouter(
    prefix="/drivers",
    tags=["Drivers"],
)


@router.get("/", response_model=list[DriverResponse])
def list_drivers(db: Session = Depends(get_db)):
    drivers = get_drivers(db)

    return [
        DriverResponse(
            driver_id=driver.driver_id,
            driver_code=driver.driver_code,
            driver_number=driver.driver_number,
            driver_full_name=driver.driver_full_name,
            constructor=(
                driver.constructor.constructor_name
                if driver.constructor
                else None
            ),
        )
        for driver in drivers
    ]