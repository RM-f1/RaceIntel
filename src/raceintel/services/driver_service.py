

from sqlalchemy.orm import Session

from database.models import Driver
from database.models import Constructor


def get_drivers(db: Session):
    

    return (
        db.query(Driver)
        .outerjoin(Constructor)
        .order_by(Driver.driver_full_name)
        .all()
    )