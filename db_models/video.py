# models/video.py
from typing import Optional
from uuid import UUID, uuid4

from sqlmodel import SQLModel, Field, Relationship


class Video(SQLModel, table=True):
    __tablename__ = "video"

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    run_session_id: UUID = Field(foreign_key="run_session.id")
    run_session: Optional["RunSession"] = Relationship(back_populates="videos")

    camera_index: int = Field(
        ge=0, le=4,
        description="Camera index (0~4)"
    )

    video_path: str
    
    # 錨點定位資料 (正規化座標 JSON)
    anchors: Optional[str] = Field(default=None, description="JSON string of 4 anchor points (x, y)")
    top_distance_m: Optional[float] = Field(default=None, description="Actual distance of top edge")
    bottom_distance_m: Optional[float] = Field(default=None, description="Actual distance of bottom edge")
