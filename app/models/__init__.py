"""Model SQLAlchemy — lược đồ theo plan.md §5.9.

Mọi model phải được import ở đây: `alembic/env.py` chỉ nạp module này, model
nào không xuất hiện sẽ bị autogenerate coi như "bảng lạ" và sinh lệnh DROP.
"""

from __future__ import annotations

from app.db.base import Base
from app.models.conversation import (
    CONVERSATION_STATUSES,
    MESSAGE_ROLES,
    Conversation,
    ConversationMessage,
    ConversationSuggestion,
)
from app.models.llm import CREDENTIAL_KINDS, PROVIDERS, LlmCredential, LlmSettings
from app.models.ops import AuditLog, JobRun
from app.models.outbox import OUTBOX_STATUSES, OutboxItem
from app.models.profile import PROFILE_STATUSES, Profile, ProfileEvidence
from app.models.rapport import SALES_CHECKS, EveningHook, RapportMessage, RapportRun

__all__ = [
    "CONVERSATION_STATUSES",
    "CREDENTIAL_KINDS",
    "MESSAGE_ROLES",
    "OUTBOX_STATUSES",
    "PROFILE_STATUSES",
    "PROVIDERS",
    "SALES_CHECKS",
    "AuditLog",
    "Base",
    "Conversation",
    "ConversationMessage",
    "ConversationSuggestion",
    "EveningHook",
    "JobRun",
    "LlmCredential",
    "LlmSettings",
    "OutboxItem",
    "Profile",
    "ProfileEvidence",
    "RapportMessage",
    "RapportRun",
]
