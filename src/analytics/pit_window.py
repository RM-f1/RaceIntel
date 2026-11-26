import importlib
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("raceintel.analytics.pit_window", run_name="__main__")
else:
    _canonical = importlib.import_module("raceintel.analytics.pit_window")
    sys.modules[__name__] = _canonical
