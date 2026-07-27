from src.etl.extract import extract_session
from src.etl.transform import transform_weather

session = extract_session(
    2024,
    "British Grand Prix",
    "R",
)

weather = transform_weather(session)

for record in weather[:5]:
    print(record)

print(f"\nTotal weather observations: {len(weather)}")
