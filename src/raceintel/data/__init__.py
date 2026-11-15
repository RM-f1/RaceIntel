"""RaceIntel multi-season data ingestion and synchronization package."""

__all__ = ["IngestionEngine", "run_ingest"]


def __getattr__(name: str):
    if name in ("IngestionEngine", "run_ingest"):
        from raceintel.data.ingest import IngestionEngine, run_ingest
        globals()["IngestionEngine"] = IngestionEngine
        globals()["run_ingest"] = run_ingest
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

