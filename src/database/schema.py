from src.database.connection import engine
from src.database.models import Base


def create_database() -> None:

    Base.metadata.create_all(bind=engine)


def drop_database() -> None:

    Base.metadata.drop_all(bind=engine)


def recreate_database() -> None:

    drop_database()
    create_database()
