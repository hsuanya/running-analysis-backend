import os
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from db.session import get_session
from db_models import Runner, RunSession
from response_chemas import GraphDataOut, RunnerInfoOut, AddRunnerIn, RunSessionInfoOut, UnanalyzedRunSessionInfoOut
import pandas as pd
import numpy as np
from fastapi.responses import FileResponse

router = APIRouter()

# 暫存區
TEMP_UPLOAD_DIR = "/home/hsuanya/workspace/running_analysis/backend/data/uploads_temp"
os.makedirs(TEMP_UPLOAD_DIR, exist_ok=True)
# 正式資料夾根目錄
RUN_SESSION_DIR = "/home/hsuanya/workspace/running_analysis/backend/data/run_sessions"
os.makedirs(RUN_SESSION_DIR, exist_ok=True)

@router.get("/runner", response_model=list[RunnerInfoOut])
async def get_runners(session: AsyncSession = Depends(get_session)) -> list[RunnerInfoOut]:
    runners = (await session.execute(select(Runner))).scalars().all()
    result = []

    for runner in runners:
        last_run = (
            await session.execute(
                select(RunSession)
                .where(RunSession.runner_id == runner.id)
                .where(RunSession.status != "pending")
                .order_by(RunSession.date.desc())
                .limit(1)
            )
        ).scalars().first()

        result.append(
            RunnerInfoOut(
                id=runner.id,
                name=runner.name,
                lastVideoId=last_run.id if last_run else None
            )
        )
    return result

@router.post("/runner")
async def add_runner(
    data: AddRunnerIn,
    session: AsyncSession = Depends(get_session)
) -> dict:
    runner = Runner(name=data.name)
    session.add(runner)
    await session.commit()
    await session.refresh(runner)
    return {"id": str(runner.id)}

@router.get(
    "/runner/{runner_id}/run_sessions",
    response_model=list[RunSessionInfoOut]
)
async def get_runner_run_sessions(
    runner_id: UUID,
    session: AsyncSession = Depends(get_session)
) -> list[RunSessionInfoOut]:
    runs = (await session.execute(
        select(RunSession)
        .where(RunSession.runner_id == runner_id)
        .where(RunSession.status != "pending")
        .options(
            selectinload(RunSession.runner),
            selectinload(RunSession.analysis),
        )
    )).scalars().all()
    print(runs)
    print(runs[0].analysis)

    result = []
    for run in runs:
        result.append(
            RunSessionInfoOut(
                runSessionId=run.id,
                runnerId=runner_id,
                runnerName=run.runner.name,
                date=run.date,
                cameraCount=run.camera_count,
                fps=run.fps,
                note=run.note,
                avgVelocity=round(run.analysis.avg_velocity, 3) if run.analysis else None,
                avgAcceleration=round(run.analysis.avg_acceleration, 3) if run.analysis else None,
                avgStepLength=round(run.analysis.avg_step_length, 3) if run.analysis else None,
                totalTime=round(run.analysis.total_time, 3) if run.analysis else None,
                status=run.status,
                progress=run.progress
            )
        )
    return result

@router.get(
    "/runner/{runner_id}/run_sessions/unanalyzed",
    response_model=list[UnanalyzedRunSessionInfoOut]
)
async def get_unanalyzed_run_sessions(
    runner_id: UUID,
    session: AsyncSession = Depends(get_session)
) -> list[UnanalyzedRunSessionInfoOut]:
    runs = (await session.execute(
        select(RunSession)
        .where(RunSession.runner_id == runner_id)
        .where(RunSession.status == "pending")
        .options(
            selectinload(RunSession.runner),
            selectinload(RunSession.videos),
        )
    )).scalars().all()

    result = []
    for run in runs:
        uploaded = {v.camera_index for v in run.videos}
        missing = [i for i in range(run.camera_count) if i not in uploaded]

        result.append(
            UnanalyzedRunSessionInfoOut(
                runSessionId=run.id,
                runnerId=runner_id,
                runnerName=run.runner.name,
                date=run.date,
                cameraCount=run.camera_count,
                fps=run.fps,
                note=run.note,
                unuploadedCameraIndexes=missing,
                videoPaths=[v.video_path if v else None for v in run.videos]
            )
        )
    return result

@router.get("/run_session/{run_session_id}")
async def get_run_session_info(run_session_id: UUID, session: AsyncSession = Depends(get_session)) -> RunSessionInfoOut:
    run_session = (await session.execute(
        select(RunSession)
        .where(RunSession.id == run_session_id)
        .options(
            selectinload(RunSession.runner),
            selectinload(RunSession.analysis),
        )
    )).scalars().first()
    if not run_session:
        raise HTTPException(status_code=404, detail="Run session not found")

    if run_session.status != "done":
        return RunSessionInfoOut(
            runSessionId=run_session_id,
            runnerId=run_session.runner_id,
            runnerName=run_session.runner.name,
            date=run_session.date,
            cameraCount=run_session.camera_count,
            fps=run_session.fps,
            note=run_session.note,
            status=run_session.status,
            progress=run_session.progress
        )

    analysis = run_session.analysis
    return RunSessionInfoOut(
        runSessionId=run_session_id,
        runnerId=run_session.runner_id,
        runnerName=run_session.runner.name,
        date=run_session.date,
        cameraCount=run_session.camera_count,
        fps=run_session.fps,
        note=run_session.note,
        status=run_session.status,
        progress=run_session.progress,
        totalTime=round(analysis.total_time, 3),
        avgVelocity=round(analysis.avg_velocity, 3),
        avgAcceleration=round(analysis.avg_acceleration, 3),
        avgStepLength=round(analysis.avg_step_length, 3)
    )

def build_graph(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    title: str,
    y_label: str,
    max_points: int = 200
):
    x = df[x_col].tolist()
    y = df[y_col].tolist()

    if len(x) > max_points:
        step = len(x) // max_points
        x = x[::step]
        y = y[::step]

    return {
        "title": title,
        "yLabel": y_label,
        "x": x,
        "y": y,
        "yMin": float(np.min(y)),
        "yMax": float(np.max(y)),
    }

@router.get(
    "/run_session/{run_session_id}/graphs",
    response_model=list[GraphDataOut]
)
async def get_run_session_graphs(run_session_id: UUID, session: AsyncSession = Depends(get_session)):
    run_session = (await session.execute(
        select(RunSession)
        .where(RunSession.id == run_session_id)
    )).scalars().first()
    if not run_session:
        raise HTTPException(status_code=404, detail="Run session not found")

    csv_path = os.path.join(RUN_SESSION_DIR, str(run_session.runner_id), str(run_session_id), "tracking_results/track_pose_full_data.csv")

    df = pd.read_csv(csv_path)
    df = df.sort_values("new_time")

    graphs = []

    graphs.append(
        build_graph(
            df,
            x_col="new_time",
            y_col="distance",
            title="Distance",
            y_label="Distance (m)",
        )
    )

    graphs.append(
        build_graph(
            df,
            x_col="new_time",
            y_col="velocity",
            title="Velocity",
            y_label="Velocity (m/s)",
        )
    )

    graphs.append(
        build_graph(
            df,
            x_col="new_time",
            y_col="acc_smooth",
            title="Acceleration",
            y_label="Acceleration (m/s²)",
        )
    )

    return graphs

@router.get("/run_session/{run_session_id}/video")
async def get_run_session_video(run_session_id: UUID, session: AsyncSession = Depends(get_session)) -> FileResponse:
    runner = (await session.execute(
        select(Runner)
        .options(
            selectinload(Runner.runs)
        )
        .where(Runner.runs.any(RunSession.id == run_session_id))
    )).scalars().first()

    return FileResponse(os.path.join(RUN_SESSION_DIR, str(runner.id), str(run_session_id), "tracking_results/analyzed_video_meta.mp4"))


@router.get("/temp_video/{temp_video_id}/thumbnail")
def get_thumbnail(temp_video_id: str):
    return FileResponse(f"{TEMP_UPLOAD_DIR}/{temp_video_id}.jpg")