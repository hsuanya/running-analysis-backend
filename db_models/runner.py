# models/athlete.py
from datetime import datetime
from typing import Optional, List
from uuid import UUID, uuid4

from sqlmodel import SQLModel, Field, Relationship


class Runner(SQLModel, table=True):
    __tablename__ = "runner"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str

    created_at: datetime = Field(default_factory=datetime.utcnow)

    runs: List["RunSession"] = Relationship(back_populates="runner")
