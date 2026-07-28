from sqlalchemy.orm import Session

from database.models import Constructor


def get_constructors(db: Session):
    

    return (
        db.query(Constructor)
        .order_by(Constructor.constructor_name)
        .all()
    )