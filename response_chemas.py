from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel


class RunnerInfoOut(BaseModel):
    id: UUID
    name: str
    lastVideoId: Optional[UUID]


class AddRunnerIn(BaseModel):
    name: str


class RunSessionInfoOut(BaseModel):
    runSessionId: UUID
    runnerId: UUID
    runnerName: str
    date: datetime
    cameraCount: int
    fps: int
    avgVelocity: Optional[float] = None
    avgAcceleration: Optional[float] = None
    avgStepLength: Optional[float] = None
    totalTime: Optional[float] = None
    note: str
    status: str
    progress: int = 0


class UnanalyzedRunSessionInfoOut(BaseModel):
    runSessionId: UUID
    runnerId: UUID
    runnerName: str
    date: datetime
    cameraCount: int
    fps: int
    note: str
    unuploadedCameraIndexes: List[int]
    videoPaths: List[Optional[str]]


class GraphDataOut(BaseModel):
    name: str
    y: list[float]


class GraphOut(BaseModel):
    title: str
    yLabel: str
    yMin: float
    yMax: float
    x: list[float]
    series: list[GraphDataOut]
    category: str = "metrics"


class AngleSampleOut(BaseModel):
    frame: int
    timeSec: float
    values: dict[str, Optional[float]]


class AnglesOut(BaseModel):
    columns: list[str]
    samples: list[AngleSampleOut]


class AnchorPointIn(BaseModel):
    x: float
    y: float


class AnchorResultIn(BaseModel):
    points: list[AnchorPointIn]
    topDistanceM: float
    bottomDistanceM: float


class UploadVideoInfoIn(BaseModel):
    tempVideoId: str
    anchors: Optional[AnchorResultIn] = None


class UploadAllRequest(BaseModel):
    runnerId: str
    date: str
    fps: int
    cameraCount: int
    note: str
    videos: list[UploadVideoInfoIn]


class UploadSeperatelyStatus(BaseModel):
    runnerId: str
    runSessionId: str
    isAllUploaded: bool
    unuploadedCameraIndexes: List[int]


class UploadSeperatelyNewRequest(BaseModel):
    runnerId: str
    date: str
    fps: int
    cameraCount: int
    note: str
    cameraIndex: int
    tempVideoId: str
    anchors: Optional[AnchorResultIn] = None


class UploadSeperatelySelectRequest(BaseModel):
    runnerId: str
    runSessionId: str
    cameraIndex: int
    tempVideoId: str
    anchors: Optional[AnchorResultIn] = None
