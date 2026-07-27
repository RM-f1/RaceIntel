from src.etl.extract import extract_session

session = extract_session(
    2024,
    "British Grand Prix",
    "R",
)

print(session.event["EventName"])
print(session.name)
