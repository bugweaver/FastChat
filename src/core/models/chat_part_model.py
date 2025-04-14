from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .mixins.int_id_pk import IntIdPkMixin

if TYPE_CHECKING:
    from .chat_model import Chat
    from .user_model import User


class ChatParticipant(IntIdPkMixin, Base):
    chat_id: Mapped[int] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    is_admin: Mapped[bool] = mapped_column(default=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    chat: Mapped["Chat"] = relationship(back_populates="participants")
    user: Mapped["User"] = relationship(back_populates="chats")

    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", name="uq_chat_participant"),
    )
