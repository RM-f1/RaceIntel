import importlib
import sys

_canonical = importlib.import_module("raceintel.analytics.standings")
sys.modules[__name__] = _canonical
