"""Persistence ports + in-memory adapters for the payments subsystem.

Postgres adapters mirror ``billing/repository.py`` and land in a follow-up
together with the migration (``infra/postgres/migrations/0XX_payments.sql``).
For now the in-memory repos back the unit tests and local runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from wapsell.payments.models import (
    Commission,
    ConnectionStatus,
    MerchantConnection,
    Payment,
    PaymentLink,
    PaymentProvider,
)


@runtime_checkable
class MerchantConnectionRepositoryPort(Protocol):
    def add(self, connection: MerchantConnection) -> MerchantConnection: ...
    def get(self, connection_id: str) -> MerchantConnection | None: ...
    def active_for(
        self, tenant_id: str, provider: PaymentProvider
    ) -> MerchantConnection | None: ...
    def list_for(self, tenant_id: str) -> list[MerchantConnection]: ...
    def update(self, connection: MerchantConnection) -> MerchantConnection: ...


@runtime_checkable
class PaymentLinkRepositoryPort(Protocol):
    def add(self, link: PaymentLink) -> PaymentLink: ...
    def get(self, link_id: str) -> PaymentLink | None: ...
    def get_by_reference(self, external_reference: str) -> PaymentLink | None: ...
    def update(self, link: PaymentLink) -> PaymentLink: ...


@runtime_checkable
class PaymentRepositoryPort(Protocol):
    def add(self, payment: Payment) -> Payment: ...
    def get_by_provider_id(self, provider_payment_id: str) -> Payment | None: ...


@runtime_checkable
class CommissionRepositoryPort(Protocol):
    def add(self, commission: Commission) -> Commission: ...
    def list_for(self, tenant_id: str) -> list[Commission]: ...


@dataclass(slots=True)
class InMemoryMerchantConnectionRepository:
    _by_id: dict[str, MerchantConnection] = field(default_factory=dict)

    def add(self, connection: MerchantConnection) -> MerchantConnection:
        self._by_id[connection.id] = connection
        return connection

    def get(self, connection_id: str) -> MerchantConnection | None:
        return self._by_id.get(connection_id)

    def active_for(
        self, tenant_id: str, provider: PaymentProvider
    ) -> MerchantConnection | None:
        return next(
            (
                c
                for c in self._by_id.values()
                if c.tenant_id == tenant_id
                and c.provider == provider
                and c.status == ConnectionStatus.ACTIVE
            ),
            None,
        )

    def list_for(self, tenant_id: str) -> list[MerchantConnection]:
        return sorted(
            (c for c in self._by_id.values() if c.tenant_id == tenant_id),
            key=lambda c: c.created_at,
            reverse=True,
        )

    def update(self, connection: MerchantConnection) -> MerchantConnection:
        if connection.id not in self._by_id:
            raise KeyError(f"unknown connection: {connection.id}")
        self._by_id[connection.id] = connection
        return connection


@dataclass(slots=True)
class InMemoryPaymentLinkRepository:
    _by_id: dict[str, PaymentLink] = field(default_factory=dict)

    def add(self, link: PaymentLink) -> PaymentLink:
        self._by_id[link.id] = link
        return link

    def get(self, link_id: str) -> PaymentLink | None:
        return self._by_id.get(link_id)

    def get_by_reference(self, external_reference: str) -> PaymentLink | None:
        return next(
            (
                link
                for link in self._by_id.values()
                if link.external_reference == external_reference
            ),
            None,
        )

    def update(self, link: PaymentLink) -> PaymentLink:
        if link.id not in self._by_id:
            raise KeyError(f"unknown link: {link.id}")
        self._by_id[link.id] = link
        return link


@dataclass(slots=True)
class InMemoryPaymentRepository:
    _by_id: dict[str, Payment] = field(default_factory=dict)

    def add(self, payment: Payment) -> Payment:
        self._by_id[payment.id] = payment
        return payment

    def get_by_provider_id(self, provider_payment_id: str) -> Payment | None:
        return next(
            (
                p
                for p in self._by_id.values()
                if p.provider_payment_id == provider_payment_id
            ),
            None,
        )


@dataclass(slots=True)
class InMemoryCommissionRepository:
    _by_id: dict[str, Commission] = field(default_factory=dict)

    def add(self, commission: Commission) -> Commission:
        self._by_id[commission.id] = commission
        return commission

    def list_for(self, tenant_id: str) -> list[Commission]:
        return sorted(
            (c for c in self._by_id.values() if c.tenant_id == tenant_id),
            key=lambda c: c.created_at,
            reverse=True,
        )
