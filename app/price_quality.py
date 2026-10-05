"""Conservative price quarantine; never changes availability or drops a product."""
from decimal import Decimal, InvalidOperation


def suspected_preorder_placeholder(price, currency, category, available, state):
    # Restrict the heuristic to major-unit currencies and unavailable sealed
    # preorder pages. Cheap singles, accessories and live offers stay intact.
    if available is not False or str(state).upper() != "PREORDER_PAGE":
        return False
    if str(category).upper() != "SEALED":
        return False
    if str(currency).upper() not in {"USD", "CAD", "AUD", "NZD", "EUR", "GBP"}:
        return False
    try:
        value = Decimal(str(price))
        return value.is_finite() and Decimal("0") <= value <= Decimal("1")
    except (InvalidOperation, ValueError, TypeError):
        return False
