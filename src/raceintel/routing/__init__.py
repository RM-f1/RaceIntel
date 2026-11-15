"""
RaceIntel Routing Module.

Provides database-driven entity resolution and domain guards.
"""

from raceintel.routing.entity_registry import (
    EntityRegistry,
    EventResolution,
    CircuitResolution,
    DriverResolution,
    ConstructorResolution,
    normalize_text,
)
from raceintel.routing.domain_guard import (
    DomainGuard,
    DomainStatus,
    DomainValidationResult,
)
from raceintel.routing.intent_classifier import (
    Intent,
    IntentResult,
    IntentClassifier,
)
from raceintel.routing.query_planner import (
    QueryPlan,
    QueryPlanner,
)

__all__ = [
    "EntityRegistry",
    "EventResolution",
    "CircuitResolution",
    "DriverResolution",
    "ConstructorResolution",
    "normalize_text",
    "DomainGuard",
    "DomainStatus",
    "DomainValidationResult",
    "Intent",
    "IntentResult",
    "IntentClassifier",
    "QueryPlan",
    "QueryPlanner",
]


