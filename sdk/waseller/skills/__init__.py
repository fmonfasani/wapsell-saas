"""Skills subsystem — deterministic, testable, LLM-invocable sales capabilities.

Each skill is a stateless class that takes context + params and returns a
SkillResult. Skills never call LLMs directly; they are the *glue* between the
SOUL prompt and external data (catalog, conversation history, buyer memory).
"""

from waseller.skills.base import SkillBase, SkillResult
from waseller.skills.catalog_lookup import CatalogLookupSkill
from waseller.skills.lead_qualifier import LeadQualifierSkill
from waseller.skills.registry import SkillRegistry
from waseller.skills.sales_closer import SalesCloserSkill

__all__ = [
    "CatalogLookupSkill",
    "LeadQualifierSkill",
    "SalesCloserSkill",
    "SkillBase",
    "SkillRegistry",
    "SkillResult",
]
