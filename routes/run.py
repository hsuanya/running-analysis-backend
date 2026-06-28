import os
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from db.session import get_session
from db_models import Runner, RunSession
from response_chemas import GraphDataOut, GraphSeriesOut, RunnerInfoOut, AddRunnerIn, RunSessionInfoOut, UnanalyzedRunSessionInfoOut
import pandas as pd
import numpy as np
from fastapi.responses import FileResponse
from utils.report_generator import generate_pdf_report

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
                avgVelocity=round(run.analysis.avg_velocity, 3) if run.analysis and run.analysis.avg_velocity is not None else None,
                avgAcceleration=round(run.analysis.avg_acceleration, 3) if run.analysis and run.analysis.avg_acceleration is not None else None,
                avgStepLength=round(run.analysis.avg_step_length, 3) if run.analysis and run.analysis.avg_step_length is not None else None,
                totalTime=round(run.analysis.total_time, 3) if run.analysis and run.analysis.total_time is not None else None,
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
        totalTime=round(analysis.total_time, 3) if analysis.total_time is not None else None,
        avgVelocity=round(analysis.avg_velocity, 3) if analysis.avg_velocity is not None else None,
        avgAcceleration=round(analysis.avg_acceleration, 3) if analysis.avg_acceleration is not None else None,
        avgStepLength=round(analysis.avg_step_length, 3) if analysis.avg_step_length is not None else None
    )

@router.delete("/run_session/{run_session_id}")
async def delete_run_session(run_session_id: UUID, session: AsyncSession = Depends(get_session)):
    import shutil
    from db_models import AnalysisMeta

    run_session = (await session.execute(
        select(RunSession)
        .where(RunSession.id == run_session_id)
        .options(selectinload(RunSession.videos))
    )).scalars().first()

    if not run_session:
        raise HTTPException(status_code=404, detail="Run session not found")

    # 1. Delete original camera video files on disk
    for video in run_session.videos:
        if video.video_path and os.path.exists(video.video_path):
            try:
                os.remove(video.video_path)
            except Exception:
                pass

    # 2. Delete result directory on disk (which has CSVs, generated charts, and report PDF)
    if run_session.result_dir and os.path.exists(run_session.result_dir):
        try:
            shutil.rmtree(run_session.result_dir)
        except Exception:
            pass

    # 3. Clean up database entries
    # Delete related analysis_meta row
    analysis = (await session.execute(
        select(AnalysisMeta).where(AnalysisMeta.run_session_id == run_session_id)
    )).scalars().first()
    if analysis:
        await session.delete(analysis)

    # Delete related video rows
    for video in run_session.videos:
        await session.delete(video)

    # Delete the run session row
    await session.delete(run_session)

    await session.commit()
    return {"status": "success", "message": "Run session deleted successfully"}

@router.delete("/runner/{runner_id}")
async def delete_runner(runner_id: UUID, session: AsyncSession = Depends(get_session)):
    import shutil
    from db_models import RunSession, AnalysisMeta, Video

    # 1. Fetch runner
    runner = (await session.execute(
        select(Runner).where(Runner.id == runner_id)
    )).scalars().first()

    if not runner:
        raise HTTPException(status_code=404, detail="Runner not found")

    # 2. Fetch all run sessions for this runner
    runs = (await session.execute(
        select(RunSession)
        .where(RunSession.runner_id == runner_id)
        .options(selectinload(RunSession.videos))
    )).scalars().all()

    # 3. For each run session, delete files and DB child entries
    for run in runs:
        # Delete original camera video files on disk
        for video in run.videos:
            if video.video_path and os.path.exists(video.video_path):
                try:
                    os.remove(video.video_path)
                except Exception:
                    pass

        # Delete result directory on disk
        if run.result_dir and os.path.exists(run.result_dir):
            try:
                shutil.rmtree(run.result_dir)
            except Exception:
                pass

        # Delete related analysis_meta row
        analysis = (await session.execute(
            select(AnalysisMeta).where(AnalysisMeta.run_session_id == run.id)
        )).scalars().first()
        if analysis:
            await session.delete(analysis)

        # Delete related video rows
        for video in run.videos:
            await session.delete(video)

        # Delete the run session row
        await session.delete(run)

    # 4. Delete the runner row
    await session.delete(runner)

    await session.commit()
    return {"status": "success", "message": "Runner and all associated sessions deleted successfully"}

def build_graph(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    title: str,
    y_label: str,
    category: str = "metrics",
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
        "series": [{"name": "main", "y": y}],
        "yMin": float(np.min(y)),
        "yMax": float(np.max(y)),
        "category": category,
    }


def build_paired_graph(
    df: pd.DataFrame,
    x_col: str,
    left_col: str,
    right_col: str,
    title: str,
    y_label: str,
    max_points: int = 200
):
    """Build a graph with two series (left / right) sharing the same x-axis."""
    x      = df[x_col].tolist()
    left_y = df[left_col].tolist()
    right_y = df[right_col].tolist()

    if len(x) > max_points:
        step = len(x) // max_points
        x       = x[::step]
        left_y  = left_y[::step]
        right_y = right_y[::step]

    all_y = left_y + right_y
    return {
        "title": title,
        "yLabel": y_label,
        "x": x,
        "series": [
            {"name": "left",  "y": left_y},
            {"name": "right", "y": right_y},
        ],
        "yMin": float(np.min(all_y)),
        "yMax": float(np.max(all_y)),
        "category": "angles",
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

    results_dir = os.path.join(RUN_SESSION_DIR, str(run_session.runner_id), str(run_session_id))
    graphs = []

    # ━━ 追蹤指標（3 張）━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    metrics_path = os.path.join(results_dir, "metrics.csv")
    if not os.path.exists(metrics_path):
        metrics_path = os.path.join(results_dir, "tracking_results", "run_metrics.csv")

    if os.path.exists(metrics_path):
        df = pd.read_csv(metrics_path)
        if "time_s" not in df.columns:
            if "absolute_frame" in df.columns:
                df["time_s"] = df["absolute_frame"] / (run_session.fps or 60.0)
            elif "frame" in df.columns:
                df["time_s"] = df["frame"] / (run_session.fps or 60.0)
        
        if "time_s" in df.columns:
            df = df.sort_values("time_s")

        for y_col, title, ylabel in [
            ("dist_m",    "Distance",     "Distance (m)"),
            ("speed_mps", "Velocity",     "Velocity (m/s)"),
            ("accel_mps2","Acceleration", "Acceleration (m/s\u00b2)"),
        ]:
            if y_col in df.columns:
                graphs.append(build_graph(df, x_col="time_s", y_col=y_col,
                                          title=title, y_label=ylabel,
                                          category="metrics"))

    # ━━ 關節角度（3 對 + 1 單）━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    angles_path = os.path.join(results_dir, "angles.csv")
    if not os.path.exists(angles_path):
        angles_path = os.path.join(results_dir, "tracking_results", "joint_angles.csv")

    if os.path.exists(angles_path):
        adf = pd.read_csv(angles_path)
        if "time_s" not in adf.columns:
            if "absolute_frame" in adf.columns:
                adf["time_s"] = adf["absolute_frame"] / (run_session.fps or 60.0)
            elif "frame" in adf.columns:
                adf["time_s"] = adf["frame"] / (run_session.fps or 60.0)

        if "time_s" in adf.columns:
            adf = adf.sort_values("time_s")

        # Paired: left + right on the same chart
        paired_cols = [
            ("left_knee_angle",          "right_knee_angle",         "Knee Angle",    "Angle (deg)"),
            ("left_hip_angle",           "right_hip_angle",          "Hip Angle",     "Angle (deg)"),
            ("left_elbow_flexion_angle", "right_elbow_flexion_angle","Elbow Flexion", "Angle (deg)"),
        ]
        for left_col, right_col, title, ylabel in paired_cols:
            if left_col in adf.columns and right_col in adf.columns:
                graphs.append(build_paired_graph(
                    adf, x_col="time_s",
                    left_col=left_col, right_col=right_col,
                    title=title, y_label=ylabel,
                ))

        # Single: standalone chart
        single_cols = [
            ("pelvis_torso_angle", "Pelvis-Torso Angle", "Angle (deg)"),
        ]
        for y_col, title, ylabel in single_cols:
            if y_col in adf.columns:
                graphs.append(build_graph(adf, x_col="time_s", y_col=y_col,
                                          title=title, y_label=ylabel,
                                          category="angles"))
    return graphs

@router.get("/run_session/{run_session_id}/video")
async def get_run_session_video(run_session_id: UUID, session: AsyncSession = Depends(get_session)) -> FileResponse:
    run_session = (await session.execute(
        select(RunSession)
        .options(selectinload(RunSession.analysis))
        .where(RunSession.id == run_session_id)
    )).scalars().first()

    if not run_session:
        raise HTTPException(status_code=404, detail="Run session not found")

    video_path = None
    if run_session.analysis and run_session.analysis.summary:
        if isinstance(run_session.analysis.summary, dict):
            video_path = run_session.analysis.summary.get("uncropped_video")

    if not video_path or not os.path.exists(video_path):
        results_dir = os.path.join(RUN_SESSION_DIR, str(run_session.runner_id), str(run_session_id))
        import glob
        matches = glob.glob(os.path.join(results_dir, "*_uncropped_2D.mp4"))
        if matches:
            video_path = matches[0]
        else:
            video_path = os.path.join(results_dir, "sequential_tracked.mp4")
            if not os.path.exists(video_path):
                video_path = os.path.join(results_dir, "tracking_results", "output_final.mp4")

    if not video_path or not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Video not found")

    return FileResponse(video_path)


@router.get("/temp_video/{temp_video_id}/thumbnail")
def get_thumbnail(temp_video_id: str):
    return FileResponse(f"{TEMP_UPLOAD_DIR}/{temp_video_id}.jpg")

@router.get("/run_session/{run_session_id}/csv")
async def get_run_session_csv(
    run_session_id: UUID,
    session: AsyncSession = Depends(get_session)
) -> FileResponse:
    run_session = (await session.execute(
        select(RunSession)
        .where(RunSession.id == run_session_id)
    )).scalars().first()
    if not run_session:
        raise HTTPException(status_code=404, detail="Run session not found")

    results_dir = os.path.join(RUN_SESSION_DIR, str(run_session.runner_id), str(run_session_id))
    angles_path = os.path.join(results_dir, "angles.csv")
    if not os.path.exists(angles_path):
        angles_path = os.path.join(results_dir, "tracking_results", "joint_angles.csv")

    if not os.path.exists(angles_path):
        raise HTTPException(status_code=404, detail="CSV file not found")

    return FileResponse(
        angles_path,
        media_type="text/csv",
        filename=f"angles_{run_session_id}.csv"
    )

@router.get("/run_session/{run_session_id}/pdf")
async def get_run_session_pdf(
    run_session_id: UUID,
    session: AsyncSession = Depends(get_session)
) -> FileResponse:
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

    results_dir = os.path.join(RUN_SESSION_DIR, str(run_session.runner_id), str(run_session_id))
    pdf_path = os.path.join(results_dir, "report.pdf")

    # Generate if not cached
    if not os.path.exists(pdf_path):
        if run_session.status != "done" or not run_session.analysis:
            raise HTTPException(status_code=400, detail="Run session is not fully analyzed yet")
        
        # Prepare session info dict
        run_session_info = {
            "id": str(run_session_id),
            "runnerName": run_session.runner.name,
            "date": run_session.date,
            "fps": run_session.fps,
            "cameraCount": run_session.camera_count,
            "totalTime": run_session.analysis.total_time,
            "avgVelocity": run_session.analysis.avg_velocity,
            "avgAcceleration": run_session.analysis.avg_acceleration,
            "avgStepLength": run_session.analysis.avg_step_length,
            "note": run_session.note,
            "status": run_session.status
        }
        
        try:
            generate_pdf_report(run_session_info, results_dir, pdf_path)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {str(e)}")

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"Runner_Analysis_Report_{run_session_id}.pdf"
    )