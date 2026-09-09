"""Lotus major-retailer package • Step 6K-3A Walmart validation • Bot release 1.0.6."""

from .catalog import load_builtin_major_retailer_definitions

load_builtin_major_retailer_definitions()

# Register retailer-specific adapters only after definitions exist.
from . import target as _target  # noqa: E402,F401
from . import walmart as _walmart  # noqa: E402,F401

from .base import (  # noqa: E402,F401
    MajorRetailerAdapter,
    MajorRetailerCapabilityProfile,
    MajorRetailerDefinition,
    MajorRetailerProbe,
    MajorRetailerProduct,
)
from .families import (  # noqa: E402,F401
    list_adapter_families,
    recommend_adapter_family,
)
from .monitor import (  # noqa: E402,F401
    get_major_retailer_catalog_status,
    get_major_retailer_framework_status,
    probe_major_retailer,
    scan_major_retailer,
)
from .onboarding import (  # noqa: E402,F401
    detect_major_retailer,
    get_major_retailer_onboarding_status,
    list_staged_major_retailers,
    normalize_major_domain,
    stage_major_retailer,
)
from .pipeline import (  # noqa: E402,F401
    demote_major_retailer,
    ensure_major_pipeline_schema,
    get_major_pipeline_status,
    get_major_promotion_gate,
    list_major_pipeline_states,
    promote_major_retailer,
    run_major_retailer_monitor,
    run_major_retailer_pipeline_scan,
    set_major_kill_switch,
    validate_major_retailer,
)
from .registry import (  # noqa: E402,F401
    build_major_retailer_adapter,
    get_major_retailer_adapter_class,
    get_major_retailer_definition,
    list_major_retailer_definitions,
    list_registered_major_retailer_adapters,
    major_retailer_adapter,
    normalize_retailer_key,
    register_major_retailer_adapter,
)

VERSION = "1.0.6"
STEP = "6K-2C"
