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

class GraphDataOut(BaseModel):
    title: str
    yLabel: str
    yMin: float
    yMax: float
    x: list[float]
    y: list[float]

class UploadAllRequest(BaseModel):
    runnerId: str
    date: str
    fps: int
    cameraCount: int
    note: str
    tempVideoIds: list[str]

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

class UploadSeperatelySelectRequest(BaseModel):
    runnerId: str
    runSessionId: str
    cameraIndex: int
    tempVideoId: str