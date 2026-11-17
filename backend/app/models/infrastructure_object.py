from sqlalchemy import Float, ForeignKey, Integer, String, Text
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
