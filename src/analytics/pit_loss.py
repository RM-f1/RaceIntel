import importlib
import sys

_canonical = importlib.import_module("raceintel.analytics.pit_loss")
sys.modules[__name__] = _canonical
