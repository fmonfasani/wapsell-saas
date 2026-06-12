"""Subscription persistence — port + InMemory + Postgres adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from waseller.billing.models import Subscription, SubscriptionStatus


@runtime_checkable
class SubscriptionRepositoryPort(Protocol):
    """Persistence boundary for subscriptions."""

    def add(self, subscription: Subscription) -> Subscription: ...
    def get(self, subscription_id: str) -> Subscription | None: ...
    def get_by_preapproval_id(self, preapproval_id: str) -> Subscription | None: ...
    def list_for(self, tenant_id: str) -> list[Subscription]: ...
    def active_for_tenant(self, tenant_id: str) -> Subscription | None: ...
    def update(self, subscription: Subscription) -> Subscription: ...


@dataclass(slots=True)
class InMemorySubscriptionRepository:
    _by_id: dict[str, Subscription] = field(default_factory=dict)

    def add(self, subscription: Subscription) -> Subscription:
        self._by_id[subscription.id] = subscription
        return subscription

    def get(self, subscription_id: str) -> Subscription | None:
        return self._by_id.get(subscription_id)

    def get_by_preapproval_id(self, preapproval_id: str) -> Subscription | None:
        return next(
            (
                s
                for s in self._by_id.values()
                if s.mp_preapproval_id == preapproval_id
            ),
            None,
        )

    def list_for(self, tenant_id: str) -> list[Subscription]:
        return sorted(
            (s for s in self._by_id.values() if s.tenant_id == tenant_id),
            key=lambda s: s.created_at,
            reverse=True,
        )

    def active_for_tenant(self, tenant_id: str) -> Subscription | None:
        """The 'currently paying' subscription for a tenant. We accept
        AUTHORIZED as active; PAUSED and PENDING don't count for
        feature-gating (caller pays nothing yet)."""
        return next(
            (
                s
                for s in self.list_for(tenant_id)
                if s.status == SubscriptionStatus.AUTHORIZED
            ),
            None,
        )

    def update(self, subscription: Subscription) -> Subscription:
        if subscription.id not in self._by_id:
            raise KeyError(f"unknown subscription: {subscription.id}")
        self._by_id[subscription.id] = subscription
        return subscription


_SUB_COLS = (
    "id, tenant_id, plan_code, status, mp_preapproval_id, mp_init_point, "
    "payer_email, started_at, current_period_end, created_at, updated_at"
)

_SUB_INSERT_SQL = (
    f"INSERT INTO subscriptions ({_SUB_COLS}) "  # noqa: S608
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)
_SUB_UPDATE_SQL = (
    "UPDATE subscriptions SET "
    "plan_code = %s, status = %s, mp_preapproval_id = %s, mp_init_point = %s, "
    "payer_email = %s, started_at = %s, current_period_end = %s, updated_at = %s "
    "WHERE id = %s"
)
_SUB_GET_SQL = f"SELECT {_SUB_COLS} FROM subscriptions WHERE id = %s"  # noqa: S608
_SUB_GET_BY_PA_SQL = (
    f"SELECT {_SUB_COLS} FROM subscriptions "  # noqa: S608
    "WHERE mp_preapproval_id = %s LIMIT 1"
)
_SUB_LIST_SQL = (
    f"SELECT {_SUB_COLS} FROM subscriptions "  # noqa: S608
    "WHERE tenant_id = %s ORDER BY created_at DESC"
)
_SUB_ACTIVE_SQL = (
    f"SELECT {_SUB_COLS} FROM subscriptions "  # noqa: S608
    "WHERE tenant_id = %s AND status = 'authorized' "
    "ORDER BY created_at DESC LIMIT 1"
)


class PostgresSubscriptionRepository:
    """Postgres-backed subscription repo. Schema:
    ``infra/postgres/migrations/011_subscriptions.sql``."""

    def __init__(self, connection: Any) -> None:  # noqa: ANN401 — DB-API
        self._conn = connection

    def add(self, subscription: Subscription) -> Subscription:
        with self._conn.cursor() as cur:
            cur.execute(_SUB_INSERT_SQL, self._row(subscription))
        self._conn.commit()
        return subscription

    def get(self, subscription_id: str) -> Subscription | None:
        with self._conn.cursor() as cur:
            cur.execute(_SUB_GET_SQL, (subscription_id,))
            rows = cur.fetchall()
        return _row_to_sub(rows[0]) if rows else None

    def get_by_preapproval_id(self, preapproval_id: str) -> Subscription | None:
        with self._conn.cursor() as cur:
            cur.execute(_SUB_GET_BY_PA_SQL, (preapproval_id,))
            rows = cur.fetchall()
        return _row_to_sub(rows[0]) if rows else None

    def list_for(self, tenant_id: str) -> list[Subscription]:
        with self._conn.cursor() as cur:
            cur.execute(_SUB_LIST_SQL, (tenant_id,))
            rows = cur.fetchall()
        return [_row_to_sub(r) for r in rows]

    def active_for_tenant(self, tenant_id: str) -> Subscription | None:
        with self._conn.cursor() as cur:
            cur.execute(_SUB_ACTIVE_SQL, (tenant_id,))
            rows = cur.fetchall()
        return _row_to_sub(rows[0]) if rows else None

    def update(self, subscription: Subscription) -> Subscription:
        with self._conn.cursor() as cur:
            cur.execute(
                _SUB_UPDATE_SQL,
                (
                    subscription.plan_code,
                    subscription.status.value
                    if isinstance(subscription.status, SubscriptionStatus)
                    else subscription.status,
                    subscription.mp_preapproval_id,
                    subscription.mp_init_point,
                    subscription.payer_email,
                    subscription.started_at,
                    subscription.current_period_end,
                    subscription.updated_at,
                    subscription.id,
                ),
            )
        self._conn.commit()
        return subscription

    @staticmethod
    def _row(s: Subscription) -> tuple[Any, ...]:
        return (
            s.id,
            s.tenant_id,
            s.plan_code,
            s.status.value if isinstance(s.status, SubscriptionStatus) else s.status,
            s.mp_preapproval_id,
            s.mp_init_point,
            s.payer_email,
            s.started_at,
            s.current_period_end,
            s.created_at,
            s.updated_at,
        )


def _row_to_sub(row: Any) -> Subscription:  # noqa: ANN401
    created = row[9]
    updated = row[10]
    if isinstance(created, str):
        created = datetime.fromisoformat(created)
    if isinstance(updated, str):
        updated = datetime.fromisoformat(updated)
    started = row[7]
    if isinstance(started, str):
        started = datetime.fromisoformat(started)
    period_end = row[8]
    if isinstance(period_end, str):
        period_end = datetime.fromisoformat(period_end)
    return Subscription(
        id=row[0],
        tenant_id=row[1],
        plan_code=row[2],
        status=SubscriptionStatus(row[3]),
        mp_preapproval_id=row[4],
        mp_init_point=row[5],
        payer_email=row[6],
        started_at=started,
        current_period_end=period_end,
        created_at=created,
        updated_at=updated,
    )
