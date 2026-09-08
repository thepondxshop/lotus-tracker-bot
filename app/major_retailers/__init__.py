"""Lotus Step 6K-1C1 major-retailer package."""

from .catalog import load_builtin_major_retailer_definitions

load_builtin_major_retailer_definitions()

# Register retailer-specific adapters only after definitions exist.
from . import target as _target  # noqa: E402,F401

from .base import (  # noqa: E402,F401
    MajorRetailerAdapter,
    MajorRetailerCapabilityProfile,
    MajorRetailerDefinition,
    MajorRetailerProbe,
    MajorRetailerProduct,
)
from .monitor import (  # noqa: E402,F401
    get_major_retailer_catalog_status,
    get_major_retailer_framework_status,
    probe_major_retailer,
    scan_major_retailer,
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

VERSION = "1.3.0"
STEP = "6K-1C1"
