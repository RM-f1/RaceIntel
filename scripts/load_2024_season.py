import fastf1

from etl.pipeline import run_pipeline


def main():
    season = 2024

    schedule = fastf1.get_event_schedule(season)

    # Skip pre-season testing
    schedule = schedule[schedule["RoundNumber"] > 0]

    total = len(schedule)

    print(f"\nLoading {total} races for {season}\n")

    for idx, (_, event) in enumerate(schedule.iterrows(), start=1):

        race_name = event["EventName"]

        print(f"[{idx}/{total}] {race_name}")

        try:
            run_pipeline(
                year=season,
                grand_prix=race_name,
                session_type="R",
            )

        except Exception as e:
            print(f"Failed: {race_name}")
            print(e)

    print("\nSeason ETL complete.")


if __name__ == "__main__":
    main()