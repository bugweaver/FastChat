from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .mixins.int_id_pk import IntIdPkMixin

if TYPE_CHECKING:
    from .attachment_model import Attachment
    from .chat_model import Chat
    from .user_model import User


class Message(IntIdPkMixin, Base):
    content: Mapped[str] = mapped_column()
    sender_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    chat_id: Mapped[int] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), index=True
    )
    reply_to_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "messages.id", ondelete="SET NULL", name="fk_messages_reply_to_id_messages"
        ),
        nullable=True,
        index=True,
    )
    is_read: Mapped[bool] = mapped_column(default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    sender: Mapped["User"] = relationship(
        back_populates="messages_sent", foreign_keys=[sender_id]
    )
    chat: Mapped["Chat"] = relationship(back_populates="messages")

    reply_to: Mapped[Optional["Message"]] = relationship(
        "Message",
        remote_side="Message.id",
        back_populates="replies",
        foreign_keys=[reply_to_id],
    )
    replies: Mapped[List["Message"]] = relationship(
        "Message", back_populates="reply_to", foreign_keys=[reply_to_id]
    )

    attachments: Mapped[List["Attachment"]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )
