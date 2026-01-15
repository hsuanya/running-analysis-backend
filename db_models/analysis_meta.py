# models/analysis_meta.py
from typing import Optional, Dict
from uuid import UUID

from sqlmodel import SQLModel, Field, Relationship, Column
from sqlalchemy import JSON


class AnalysisMeta(SQLModel, table=True):
    __tablename__ = "analysis_meta"

    run_session_id: UUID = Field(
        foreign_key="run_session.id",
        primary_key=True
    )

    total_time: float = Field()
    avg_velocity: float = Field()
    avg_acceleration: float = Field()
    avg_step_length: float = Field()

    summary: Optional[Dict] = Field(
        sa_column=Column(JSON),
        description="High-level analysis summary (JSON)"
    )

    run_session: Optional["RunSession"] = Relationship(back_populates="analysis")
