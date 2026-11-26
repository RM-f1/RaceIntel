from database.connection import query_to_dataframe as q

print(q("SELECT COUNT(*) AS n FROM laps WHERE tyre_compound = 'None'", {}))