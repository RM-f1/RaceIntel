from src.database.connection import SessionLocal, engine

print("Database:", engine.url)

db = SessionLocal()
from src.database.schema import recreate_database
from src.etl.pipeline import run_pipeline


def main():

    # recreate_database()

    run_pipeline(
        year=2024,
        grand_prix="British Grand Prix",
        session_type="R",
    )


if __name__ == "__main__":
    main()
