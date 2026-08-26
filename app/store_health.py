from datetime import datetime

from sqlalchemy import (
    func,
    select,
)

from app.database import (
    SessionLocal,
)

from app.models import (
    Store,
)


# =========================================================
# LOTUS STORE HEALTH ENGINE
# PonDeX Trackers
# Version 0.6.3
# =========================================================


DEGRADED_AFTER = 1

UNHEALTHY_AFTER = 3

AUTO_DISABLE_AFTER = 5


# =========================================================
# SUCCESS
# =========================================================

async def record_store_success(
    store_id: int,
    allow_health_reenable: bool = False,
):

    if SessionLocal is None:

        raise RuntimeError(
            "Database is not configured."
        )

    async with SessionLocal() as session:

        result = await session.execute(

            select(
                Store
            ).where(
                Store.id
                == store_id
            )
        )

        store = (
            result.scalar_one_or_none()
        )

        if store is None:

            return None

        now = datetime.utcnow()

        store.last_success_at = now

        store.consecutive_failures = 0

        store.last_error = None

        # -------------------------------------------------
        # AUTO-RECOVERY
        #
        # Only stores disabled by HEALTH are allowed
        # to automatically reactivate themselves.
        # -------------------------------------------------

        if (
            allow_health_reenable
            and store.disabled_reason
            == "HEALTH"
        ):

            store.active = True

            store.disabled_reason = None

            store.health_status = (
                "HEALTHY"
            )

            print(
                (
                    "STORE AUTO-RECOVERED: "
                    f"{store.name} | "
                    f"{store.domain}"
                )
            )

        elif store.active:

            store.health_status = (
                "HEALTHY"
            )

        await session.commit()

        await session.refresh(
            store
        )

        return store


# =========================================================
# FAILURE
# =========================================================

async def record_store_failure(
    store_id: int,
    error_text: str,
):

    if SessionLocal is None:

        raise RuntimeError(
            "Database is not configured."
        )

    async with SessionLocal() as session:

        result = await session.execute(

            select(
                Store
            ).where(
                Store.id
                == store_id
            )
        )

        store = (
            result.scalar_one_or_none()
        )

        if store is None:

            return None

        # Manual and removed stores are not controlled
        # by automatic health logic.

        if store.disabled_reason in (
            "MANUAL",
            "REMOVED",
        ):

            return store

        store.consecutive_failures = (
            (
                store.consecutive_failures
                or 0
            )
            + 1
        )

        store.last_failure_at = (
            datetime.utcnow()
        )

        store.last_error = (
            error_text[
                :4000
            ]
        )

        failures = (
            store.consecutive_failures
        )

        if failures >= AUTO_DISABLE_AFTER:

            store.health_status = (
                "DISABLED"
            )

            store.active = False

            store.disabled_reason = (
                "HEALTH"
            )

            print(
                (
                    "STORE AUTO-DISABLED: "
                    f"{store.name} | "
                    f"Failures={failures}"
                )
            )

        elif failures >= UNHEALTHY_AFTER:

            store.health_status = (
                "UNHEALTHY"
            )

        else:

            store.health_status = (
                "DEGRADED"
            )

        await session.commit()

        await session.refresh(
            store
        )

        return store


# =========================================================
# MANUAL DISABLE
# =========================================================

async def manual_disable_store(
    store_id: int,
):

    if SessionLocal is None:

        raise RuntimeError(
            "Database is not configured."
        )

    async with SessionLocal() as session:

        result = await session.execute(

            select(
                Store
            ).where(
                Store.id
                == store_id
            )
        )

        store = (
            result.scalar_one_or_none()
        )

        if store is None:

            return None

        store.active = False

        store.health_status = (
            "DISABLED"
        )

        store.disabled_reason = (
            "MANUAL"
        )

        await session.commit()

        await session.refresh(
            store
        )

        return store


# =========================================================
# MANUAL ENABLE
# =========================================================

async def manual_enable_store(
    store_id: int,
):

    if SessionLocal is None:

        raise RuntimeError(
            "Database is not configured."
        )

    async with SessionLocal() as session:

        result = await session.execute(

            select(
                Store
            ).where(
                Store.id
                == store_id
            )
        )

        store = (
            result.scalar_one_or_none()
        )

        if store is None:

            return None

        store.active = True

        store.health_status = (
            "HEALTHY"
        )

        store.disabled_reason = None

        store.consecutive_failures = 0

        store.last_error = None

        await session.commit()

        await session.refresh(
            store
        )

        return store


# =========================================================
# REMOVE FROM MONITORING
# =========================================================

async def mark_store_removed(
    store_id: int,
):

    if SessionLocal is None:

        raise RuntimeError(
            "Database is not configured."
        )

    async with SessionLocal() as session:

        result = await session.execute(

            select(
                Store
            ).where(
                Store.id
                == store_id
            )
        )

        store = (
            result.scalar_one_or_none()
        )

        if store is None:

            return None

        store.active = False

        store.health_status = (
            "DISABLED"
        )

        store.disabled_reason = (
            "REMOVED"
        )

        await session.commit()

        await session.refresh(
            store
        )

        return store


# =========================================================
# RESTORE REMOVED STORE
# =========================================================

async def restore_removed_store(
    store_id: int,
):

    if SessionLocal is None:

        raise RuntimeError(
            "Database is not configured."
        )

    async with SessionLocal() as session:

        result = await session.execute(

            select(
                Store
            ).where(
                Store.id
                == store_id
            )
        )

        store = (
            result.scalar_one_or_none()
        )

        if store is None:

            return None

        if store.disabled_reason != "REMOVED":

            return store

        store.active = True

        store.health_status = (
            "HEALTHY"
        )

        store.disabled_reason = None

        store.consecutive_failures = 0

        store.last_error = None

        await session.commit()

        await session.refresh(
            store
        )

        return store


# =========================================================
# HEALTH RECOVERY CANDIDATES
# =========================================================

async def get_health_recovery_candidates():

    if SessionLocal is None:

        return []

    async with SessionLocal() as session:

        result = await session.execute(

            select(
                Store
            ).where(
                Store.active
                == False
            ).where(
                Store.disabled_reason
                == "HEALTH"
            ).where(
                Store.platform
                == "shopify"
            )
        )

        return list(
            result.scalars().all()
        )


# =========================================================
# HEALTH OVERVIEW
# =========================================================

async def get_health_overview():

    if SessionLocal is None:

        return {
            "healthy": 0,
            "degraded": 0,
            "unhealthy": 0,
            "disabled": 0,
            "removed": 0,
        }

    async with SessionLocal() as session:

        result = await session.execute(

            select(
                Store
            ).where(
                Store.platform
                == "shopify"
            )
        )

        stores = list(
            result.scalars().all()
        )

    overview = {
        "healthy": 0,
        "degraded": 0,
        "unhealthy": 0,
        "disabled": 0,
        "removed": 0,
    }

    for store in stores:

        if store.disabled_reason == "REMOVED":

            overview[
                "removed"
            ] += 1

        elif store.health_status == "HEALTHY":

            overview[
                "healthy"
            ] += 1

        elif store.health_status == "DEGRADED":

            overview[
                "degraded"
            ] += 1

        elif store.health_status == "UNHEALTHY":

            overview[
                "unhealthy"
            ] += 1

        else:

            overview[
                "disabled"
            ] += 1

    return overview