from pydantic import BaseModel
from typing import Optional, List
from uuid import UUID
from datetime import datetime

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

class GraphSeriesOut(BaseModel):
    name: str          # e.g. "main", "left", "right"
    y: list[float]

class GraphDataOut(BaseModel):
    title: str
    yLabel: str
    yMin: float
    yMax: float
    x: list[float]          # shared x-axis for all series
    series: list[GraphSeriesOut]
    category: str           # "metrics" | "angles"

class AnchorPoint(BaseModel):
    x: float
    y: float

class AnchorResult(BaseModel):
    points: List[AnchorPoint]
    leftToMidDistanceM: float
    midToRightDistanceM: float

class VideoUploadInfo(BaseModel):
    tempVideoId: str
    anchors: Optional[AnchorResult] = None

class UploadAllRequest(BaseModel):
    runnerId: str
    date: str
    fps: int
    cameraCount: int
    note: str
    # 原本是 tempVideoIds: list[str]，改為包含錨點的物件列表
    videos: List[VideoUploadInfo]

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
    anchors: Optional[AnchorResult] = None

class UploadSeperatelySelectRequest(BaseModel):
    runnerId: str
    runSessionId: str
    cameraIndex: int
    tempVideoId: str
    anchors: Optional[AnchorResult] = None