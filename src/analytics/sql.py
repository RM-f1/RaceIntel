import importlib
import sys

_canonical = importlib.import_module("raceintel.analytics.sql")
sys.modules[__name__] = _canonical
