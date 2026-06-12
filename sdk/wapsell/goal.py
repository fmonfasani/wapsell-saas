"""Goal system — what the agent should accomplish and how to judge success.

A Goal is a high-level directive (e.g. "qualify this lead", "close sale for
product X"). The GoalJudge evaluates conversation context against goal criteria
and returns a deterministic score + diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
import uuid


class GoalType(StrEnum):
    QUALIFY = "qualify"
    SELL = "sell"
    LOOKUP = "lookup"
    FOLLOW_UP = "follow_up"


class GoalStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    ACHIEVED = "ACHIEVED"
    FAILED = "FAILED"


@dataclass
class Goal:
    goal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str = ""
    goal_type: GoalType = GoalType.QUALIFY
    status: GoalStatus = GoalStatus.PENDING
    params: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "tenant_id": self.tenant_id,
            "goal_type": self.goal_type.value,
            "status": self.status.value,
            "params": self.params,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class GoalResult:
    goal_id: str
    achieved: bool
    score: float
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "achieved": self.achieved,
            "score": self.score,
            "diagnostics": self.diagnostics,
        }


_QUALIFY_SCORE_THRESHOLD = 40  # min intent_score (0-100) to consider a lead qualified


class GoalJudge:
    """Deterministic goal evaluator. Scores 0.0-1.0 based on evidence in context."""

    def judge(self, goal: Goal, context: dict[str, Any]) -> GoalResult:
        if goal.goal_type is GoalType.QUALIFY:
            return self._judge_qualify(goal, context)
        if goal.goal_type is GoalType.SELL:
            return self._judge_sell(goal, context)
        if goal.goal_type is GoalType.LOOKUP:
            return self._judge_lookup(goal, context)
        return GoalResult(
            goal_id=goal.goal_id,
            achieved=False,
            score=0.0,
            diagnostics={"error": "unknown goal type"},
        )

    @staticmethod
    def _judge_qualify(goal: Goal, context: dict[str, Any]) -> GoalResult:
        score = context.get("intent_score", 0)
        tag = context.get("tag", "cold")
        achieved = score >= _QUALIFY_SCORE_THRESHOLD and tag in ("warm", "hot")
        return GoalResult(
            goal_id=goal.goal_id,
            achieved=achieved,
            score=score / 100.0,
            diagnostics={
                "intent_score": score,
                "tag": tag,
                "threshold": _QUALIFY_SCORE_THRESHOLD,
            },
        )

    @staticmethod
    def _judge_sell(goal: Goal, context: dict[str, Any]) -> GoalResult:
        stage = context.get("stage", "IDENTIFY")
        payment_confirmed = context.get("payment_confirmed", False)
        achieved = stage == "CLOSED" and payment_confirmed
        return GoalResult(
            goal_id=goal.goal_id,
            achieved=achieved,
            score=1.0 if achieved else 0.0,
            diagnostics={"stage": stage, "payment_confirmed": payment_confirmed},
        )

    @staticmethod
    def _judge_lookup(goal: Goal, context: dict[str, Any]) -> GoalResult:
        matches = context.get("matches", [])
        found = len(matches) > 0
        return GoalResult(
            goal_id=goal.goal_id,
            achieved=found,
            score=1.0 if found else 0.0,
            diagnostics={"matches_found": len(matches), "query": goal.params.get("query", "")},
        )
