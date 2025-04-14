"""Create models

Revision ID: e426c0686261
Revises:
Create Date: 2025-03-20 10:58:11.245657

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e426c0686261"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chats",
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("is_group", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_message_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chats")),
    )
    op.create_index(
        op.f("ix_chats_created_at"), "chats", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_chats_is_group"), "chats", ["is_group"], unique=False
    )
    op.create_index(
        op.f("ix_chats_last_message_at"),
        "chats",
        ["last_message_at"],
        unique=False,
    )
    op.create_index(op.f("ix_chats_name"), "chats", ["name"], unique=False)
    op.create_table(
        "users",
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("first_name", sa.String(), nullable=True),
        sa.Column("last_name", sa.String(), nullable=True),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("password", sa.String(), nullable=False),
        sa.Column("avatar", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "last_seen",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_table(
        "chat_participants",
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["chat_id"],
            ["chats.id"],
            name=op.f("fk_chat_participants_chat_id_chats"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_chat_participants_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_participants")),
        sa.UniqueConstraint("chat_id", "user_id", name="uq_chat_participant"),
    )
    op.create_index(
        op.f("ix_chat_participants_chat_id"),
        "chat_participants",
        ["chat_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chat_participants_joined_at"),
        "chat_participants",
        ["joined_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chat_participants_user_id"),
        "chat_participants",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "messages",
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("sender_id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("reply_to_id", sa.Integer(), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["chat_id"],
            ["chats.id"],
            name=op.f("fk_messages_chat_id_chats"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reply_to_id"],
            ["messages.id"],
            name="fk_messages_reply_to_id_messages",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["sender_id"],
            ["users.id"],
            name=op.f("fk_messages_sender_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
    )
    op.create_index(
        op.f("ix_messages_chat_id"), "messages", ["chat_id"], unique=False
    )
    op.create_index(
        op.f("ix_messages_created_at"),
        "messages",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_messages_is_read"), "messages", ["is_read"], unique=False
    )
    op.create_index(
        op.f("ix_messages_reply_to_id"),
        "messages",
        ["reply_to_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_messages_sender_id"), "messages", ["sender_id"], unique=False
    )
    op.create_table(
        "attachments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("file_type", sa.String(), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name=op.f("fk_attachments_message_id_messages"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attachments")),
    )
    op.create_index(
        op.f("ix_attachments_id"), "attachments", ["id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_attachments_id"), table_name="attachments")
    op.drop_table("attachments")
    op.drop_index(op.f("ix_messages_sender_id"), table_name="messages")
    op.drop_index(op.f("ix_messages_reply_to_id"), table_name="messages")
    op.drop_index(op.f("ix_messages_is_read"), table_name="messages")
    op.drop_index(op.f("ix_messages_created_at"), table_name="messages")
    op.drop_index(op.f("ix_messages_chat_id"), table_name="messages")
    op.drop_table("messages")
    op.drop_index(
        op.f("ix_chat_participants_user_id"), table_name="chat_participants"
    )
    op.drop_index(
        op.f("ix_chat_participants_joined_at"), table_name="chat_participants"
    )
    op.drop_index(
        op.f("ix_chat_participants_chat_id"), table_name="chat_participants"
    )
    op.drop_table("chat_participants")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_chats_name"), table_name="chats")
    op.drop_index(op.f("ix_chats_last_message_at"), table_name="chats")
    op.drop_index(op.f("ix_chats_is_group"), table_name="chats")
    op.drop_index(op.f("ix_chats_created_at"), table_name="chats")
    op.drop_table("chats")
