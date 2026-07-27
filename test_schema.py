import src.database.models
from src.database.connection import Base, engine

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

print("Database recreated successfully!")
