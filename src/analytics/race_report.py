import importlib
import sys

_canonical = importlib.import_module("raceintel.analytics.race_report")
sys.modules[__name__] = _canonical
