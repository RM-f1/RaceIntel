import importlib
import sys

_canonical = importlib.import_module("raceintel.analytics.weather")
sys.modules[__name__] = _canonical
