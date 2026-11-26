import importlib
import sys

_canonical = importlib.import_module("raceintel.analytics.tyre")
sys.modules[__name__] = _canonical
