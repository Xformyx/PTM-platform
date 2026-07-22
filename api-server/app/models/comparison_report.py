"""ComparisonReport model — persists comparative analysis reports and Q&A history."""

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.mysql import DATETIME as DateTime, JSON, LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ComparisonReport(Base):
    __tablename__ = "comparison_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id_a: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_id_b: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    report_text: Mapped[str | None] = mapped_column(LONGTEXT, nullable=True)
    chat_messages: Mapped[list | None] = mapped_column(JSON, nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    user_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(fsp=3), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(fsp=3), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("order_id_a", "order_id_b", "user_id", name="uq_comparison_user"),
    )
