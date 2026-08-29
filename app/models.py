from app.database import Base
from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column

class Tour(Base):
	__tablename__ = 'tours'

	id: Mapped[int] = mapped_column(primary_key=True)
	title: Mapped[str]
	language: Mapped[str]
	created_at: Mapped[datetime] = mapped_column(default=datetime.now)