from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.db.base import Base

# Ключи фото, которыми управляет API, лежат в этом префиксе bucket.
PHOTO_KEY_PREFIX = "objects/"


class InfrastructureObject(Base):
    __tablename__ = "infrastructure_objects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Имена колонок в исходной схеме заданы в camelCase.
    # В "imgUrl" хранится ключ файла в S3, а не готовая ссылка.
    img_key: Mapped[str | None] = mapped_column("imgUrl", Text)
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

    @property
    def img_url(self) -> str | None:
        """Ссылка для клиента: API-эндпоинт фото или внешний URL из старых данных."""
        if not self.img_key:
            return None
        if not self.img_key.startswith(PHOTO_KEY_PREFIX):
            return self.img_key
        if self.id is None:
            return None
        return f"{settings.api_prefix}/infrastructure-objects/{self.id}/photo"
