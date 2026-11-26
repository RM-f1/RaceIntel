import importlib
import sys

_canonical = importlib.import_module("raceintel.analytics.position")
sys.modules[__name__] = _canonical
