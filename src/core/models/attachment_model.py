from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .mixins.int_id_pk import IntIdPkMixin

if TYPE_CHECKING:
    from .message_model import Message


class Attachment(IntIdPkMixin, Base):
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    filename: Mapped[str]
    file_path: Mapped[str]
    file_type: Mapped[str]
    file_size: Mapped[int]
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    message: Mapped["Message"] = relationship(back_populates="attachments")
