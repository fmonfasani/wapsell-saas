"""Request/response validation using Pydantic.

Ensures:
- Tenant configs are valid before creation
- Messages have required fields
- Agent responses are well-formed
- Clear error messages on validation failure
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class TenantConfig(BaseModel):
    """Validated tenant configuration.

    Example:
        >>> config = TenantConfig(
        ...     name="Acme Realty",
        ...     slug="acme",
        ...     soul_system_prompt="You are a real-estate agent...",
        ... )
        >>> # Raises ValidationError if name is empty, slug has uppercase, etc.
    """

    name: str = Field(..., min_length=1, max_length=100, description="Tenant business name")
    slug: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="URL-safe slug (lowercase, hyphens, underscores only)",
    )
    soul_system_prompt: Optional[str] = Field(
        None, max_length=5000, description="Behavioral prompt override"
    )
    rate_limit_per_minute: int = Field(
        default=100, ge=1, le=10000, description="Max messages per minute"
    )

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        """Slug must be lowercase, alphanumeric, hyphens/underscores only."""
        if not all(c.isalnum() or c in "-_" for c in v):
            raise ValueError(
                "slug must contain only lowercase letters, numbers, hyphens, or underscores"
            )
        if v[0] == "-" or v[0] == "_":
            raise ValueError("slug must start with a letter or number")
        return v


class InboundMessage(BaseModel):
    """Validated inbound message from buyer.

    Example:
        >>> msg = InboundMessage(
        ...     tenant_id="acme",
        ...     buyer_id="acme:+5491234567",
        ...     text="Busco un departamento",
        ... )
    """

    tenant_id: str = Field(..., description="Tenant slug")
    buyer_id: str = Field(..., description="Canonical buyer ID (tenant:number)")
    text: str = Field(..., min_length=1, max_length=4096, description="Message text")
    timestamp: Optional[str] = Field(None, description="ISO8601 timestamp (optional)")

    @field_validator("buyer_id")
    @classmethod
    def validate_buyer_id(cls, v: str) -> str:
        """Buyer ID must be in format tenant:number."""
        if ":" not in v:
            raise ValueError("buyer_id must be in format 'tenant:number'")
        return v


class AgentResponse(BaseModel):
    """Validated agent response to buyer.

    Example:
        >>> response = AgentResponse(
        ...     reply="Tengo 3 opciones para ti...",
        ...     model="openai/gpt-4o-mini",
        ...     handoff=False,
        ... )
    """

    reply: str = Field(..., min_length=1, max_length=4096, description="Agent's text reply")
    model: str = Field(..., description="Which model generated this (e.g., openai/gpt-4o)")
    handoff: bool = Field(
        default=False, description="True if escalated to human (reply is default message)"
    )
    facts_cited: int = Field(
        default=0, ge=0, description="Number of catalog facts used"
    )
    latency_ms: float = Field(
        default=0, ge=0, description="Total time to generate response"
    )


class SkillInvocation(BaseModel):
    """Validated skill call.

    Example:
        >>> skill = SkillInvocation(
        ...     name="catalog_lookup",
        ...     params={"query": "2 ambientes"},
        ... )
    """

    name: str = Field(..., description="Skill slug (e.g., catalog_lookup)")
    params: dict = Field(default_factory=dict, description="Skill parameters")
    confidence: float = Field(
        default=0.5, ge=0, le=1, description="Confidence the skill applies (0-1)"
    )
