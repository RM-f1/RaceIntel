from src.etl.extract import extract_session

session = extract_session(
    2024,
    "British Grand Prix",
    "R",
)

print("session.name =", session.name)
print("session type =", session.session_info)
print("event format =", session.event["EventFormat"])
