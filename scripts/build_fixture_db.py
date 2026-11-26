"""Build a small, deterministic CI fixture database at tests/fixtures/ci.db.

Reads data/raceintel.db strictly in read-only URI mode (?mode=ro) and copies
a representative subset of 2022 and 2024 Race and Sprint sessions while
preserving primary-key IDs (including session_id=2) and foreign-key integrity.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = PROJECT_ROOT / "data" / "raceintel.db"
DEFAULT_DEST = PROJECT_ROOT / "tests" / "fixtures" / "ci.db"
MAX_SIZE_BYTES = 5 * 1024 * 1024

# Representative 2022 events (including Sprint weekends) plus all 2024 events
# so 2024 chronology, standings, and Sprint assertions pass within < 5 MB.
SELECTED_2022_EVENTS: tuple[str, ...] = (
    "Bahrain Grand Prix",
    "Austrian Grand Prix",
    "São Paulo Grand Prix",
    "Abu Dhabi Grand Prix",
)

REQUIRED_TABLES: tuple[str, ...] = (
    "seasons",
    "events",
    "sessions",
    "drivers",
    "constructors",
    "race_results",
    "laps",
    "weather_observations",
    "session_sync_status",
)


def _copy_rows(
    src: sqlite3.Connection,
    dst: sqlite3.Connection,
    table: str,
    where_clause: str = "",
    params: tuple = (),
) -> int:
    cols = [r[1] for r in src.execute(f"PRAGMA table_info({table})").fetchall()]
    col_list = ", ".join(cols)
    placeholders = ", ".join("?" for _ in cols)
    sql = f"SELECT {col_list} FROM {table}"
    if where_clause:
        sql += f" WHERE {where_clause}"
    rows = src.execute(sql, params).fetchall()
    if rows:
        dst.executemany(
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})",
            rows,
        )
    return len(rows)


def _validate_fixture(db_path: Path) -> dict[str, int]:
    if not db_path.is_file():
        raise RuntimeError(f"Fixture database missing: {db_path}")
    size_bytes = db_path.stat().st_size
    if size_bytes >= MAX_SIZE_BYTES:
        raise RuntimeError(
            f"Fixture size {size_bytes:,} bytes exceeds {MAX_SIZE_BYTES:,} byte limit."
        )

    conn = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        integrity = conn.execute("PRAGMA integrity_check;").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"Integrity check failed: {integrity}")

        conn.execute("PRAGMA foreign_keys = ON;")
        fk_errors = conn.execute("PRAGMA foreign_key_check;").fetchall()
        if fk_errors:
            raise RuntimeError(f"Foreign-key check failed: {fk_errors[:5]}")

        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        missing = set(REQUIRED_TABLES) - tables
        if missing:
            raise RuntimeError(f"Missing required tables: {sorted(missing)}")

        seasons = {
            r[0] for r in conn.execute("SELECT season_year FROM seasons").fetchall()
        }
        if seasons != {2022, 2024}:
            raise RuntimeError(f"Unexpected seasons in fixture: {sorted(seasons)}")

        s2 = conn.execute(
            "SELECT session_id FROM sessions WHERE session_id = 2"
        ).fetchone()
        if s2 is None:
            raise RuntimeError("Required session_id=2 is missing from fixture.")

        counts = {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in REQUIRED_TABLES
        }
        return counts
    finally:
        conn.close()


def build_fixture(
    source_path: Path = DEFAULT_SOURCE,
    dest_path: Path = DEFAULT_DEST,
    force: bool = False,
) -> dict[str, int]:
    if not source_path.is_file():
        raise FileNotFoundError(f"Source database not found: {source_path}")

    if dest_path.exists() and not force:
        raise FileExistsError(
            f"Fixture already exists at {dest_path}. Pass --force to overwrite."
        )

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    src = sqlite3.connect(f"file:{source_path.resolve().as_posix()}?mode=ro", uri=True)
    fd, tmp_name = tempfile.mkstemp(suffix=".db", dir=str(dest_path.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)

    try:
        dst = sqlite3.connect(str(tmp_path))
        try:
            dst.execute("PRAGMA foreign_keys = OFF;")
            # Copy tables first, then indexes.
            ddl_rows = src.execute(
                """
                SELECT type, name, sql FROM sqlite_master
                WHERE sql IS NOT NULL AND name != 'sqlite_sequence'
                ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 ELSE 2 END, name
                """
            ).fetchall()
            for _, _, sql in ddl_rows:
                dst.execute(sql)

            # 1. Seasons (2022 and 2024)
            _copy_rows(src, dst, "seasons", "season_year IN (2022, 2024)")
            season_ids = [
                r[0] for r in dst.execute("SELECT season_id FROM seasons").fetchall()
            ]

            # 2. Selected events: all 2024 events + selected 2022 events
            event_rows = [
                r[0]
                for r in src.execute(
                    """
                    SELECT e.event_id
                    FROM events e
                    JOIN seasons s ON s.season_id = e.season_id
                    WHERE s.season_year = 2024
                    ORDER BY e.round_number, e.event_id
                    """
                ).fetchall()
            ]
            for name in SELECTED_2022_EVENTS:
                row = src.execute(
                    """
                    SELECT e.event_id
                    FROM events e
                    JOIN seasons s ON s.season_id = e.season_id
                    WHERE s.season_year = 2022 AND e.event_name = ?
                    """,
                    (name,),
                ).fetchone()
                if row is None:
                    raise RuntimeError(
                        f"Selected event (2022, {name!r}) not found in {source_path}"
                    )
                event_rows.append(row[0])

            ev_ph = ", ".join("?" for _ in event_rows)
            _copy_rows(src, dst, "events", f"event_id IN ({ev_ph})", tuple(event_rows))

            # 3. Sessions & sync status
            _copy_rows(src, dst, "sessions", f"event_id IN ({ev_ph})", tuple(event_rows))
            session_ids = [
                r[0] for r in dst.execute("SELECT session_id FROM sessions ORDER BY session_id").fetchall()
            ]
            ss_ph = ", ".join("?" for _ in session_ids)
            _copy_rows(
                src, dst, "session_sync_status", f"session_id IN ({ss_ph})", tuple(session_ids)
            )

            # 4. Dependent fact tables
            _copy_rows(src, dst, "race_results", f"session_id IN ({ss_ph})", tuple(session_ids))
            _copy_rows(src, dst, "laps", f"session_id IN ({ss_ph})", tuple(session_ids))
            _copy_rows(
                src, dst, "weather_observations", f"session_id IN ({ss_ph})", tuple(session_ids)
            )

            # 5. Referenced drivers and constructors
            driver_ids = sorted(
                {
                    r[0]
                    for r in dst.execute("SELECT DISTINCT driver_id FROM race_results").fetchall()
                }
                | {
                    r[0]
                    for r in dst.execute("SELECT DISTINCT driver_id FROM laps").fetchall()
                }
            )
            drv_ph = ", ".join("?" for _ in driver_ids)
            _copy_rows(src, dst, "drivers", f"driver_id IN ({drv_ph})", tuple(driver_ids))

            constructor_ids = sorted(
                {
                    r[0]
                    for r in dst.execute("SELECT DISTINCT constructor_id FROM race_results").fetchall()
                }
                | {
                    r[0]
                    for r in dst.execute("SELECT DISTINCT constructor_id FROM drivers").fetchall()
                }
            )
            con_ph = ", ".join("?" for _ in constructor_ids)
            _copy_rows(
                src, dst, "constructors", f"constructor_id IN ({con_ph})", tuple(constructor_ids)
            )

            dst.commit()
            dst.execute("VACUUM;")
        finally:
            dst.close()

        os.replace(tmp_path, dest_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise
    finally:
        src.close()

    return _validate_fixture(dest_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build CI fixture SQLite database.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Explicitly allow overwriting an existing fixture file.",
    )
    args = parser.parse_args()

    counts = build_fixture(source_path=args.source, dest_path=args.dest, force=args.force)
    size_bytes = args.dest.stat().st_size
    print(f"Fixture built at {args.dest} ({size_bytes:,} bytes, {size_bytes / (1024 * 1024):.2f} MB)")
    for table, count in counts.items():
        print(f"  {table}: {count}")


if __name__ == "__main__":
    main()
