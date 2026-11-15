"""RaceIntel background synchronization service package."""

__all__ = ["SyncWorker"]


def __getattr__(name: str):
    if name == "SyncWorker":
        from raceintel.sync.worker import SyncWorker
        globals()["SyncWorker"] = SyncWorker
        return SyncWorker
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

