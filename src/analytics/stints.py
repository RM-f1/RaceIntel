import importlib
import sys

_canonical = importlib.import_module("raceintel.analytics.stints")
sys.modules[__name__] = _canonical
