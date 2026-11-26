import importlib
import sys

_canonical = importlib.import_module("raceintel.analytics.degradation_v2")
sys.modules[__name__] = _canonical
