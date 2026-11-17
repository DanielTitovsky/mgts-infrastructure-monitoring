from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class InfrastructureObject(Base):
    __tablename__ = "infrastructure_objects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Имена колонок в исходной схеме заданы в camelCase.
    img_url: Mapped[str | None] = mapped_column("imgUrl", Text)
    type: Mapped[str | None] = mapped_column(String(100))
    status_id: Mapped[int | None] = mapped_column(
        "statusId",
        ForeignKey("statuses.id", ondelete="SET NULL"),
    )
    place: Mapped[str | None] = mapped_column(Text)

    # Добавлены backend/sql/schema.sql.
    external_id: Mapped[str | None] = mapped_column(String(100))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)

    # --- Состояние обработки фото воркером (backend/sql/schema.sql) ---
    # pending -> processing -> done | failed
    processing_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    processing_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)
    processing_error: Mapped[str | None] = mapped_column(Text)
    # Фото с рамками от модели. Оригинал остаётся в img_url.
    processed_img_url: Mapped[str | None] = mapped_column(Text)
