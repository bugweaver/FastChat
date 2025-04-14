from datetime import datetime
from typing import TYPE_CHECKING, List

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .mixins.int_id_pk import IntIdPkMixin

if TYPE_CHECKING:
    from .chat_part_model import ChatParticipant
    from .message_model import Message


class Chat(IntIdPkMixin, Base):
    name: Mapped[str | None] = mapped_column(nullable=True, index=True)
    is_group: Mapped[bool] = mapped_column(default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    messages: Mapped[List["Message"]] = relationship(
        back_populates="chat", cascade="all, delete-orphan"
    )
    participants: Mapped[List["ChatParticipant"]] = relationship(
        back_populates="chat", cascade="all, delete-orphan"
    )
