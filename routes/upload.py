import os, shutil, uuid, asyncio, glob
from uuid import UUID
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from db.session import get_session, async_session
from db_models import RunSession, AnalysisMeta, Video
from analyze import track_and_draw
from datetime import datetime
import cv2
from pathlib import Path
from response_chemas import UploadSeperatelyStatus, UploadSeperatelyNewRequest, UploadSeperatelySelectRequest, UploadAllRequest

router = APIRouter()

TEMP_UPLOAD_DIR = "/home/hsuanya/workspace/running_analysis/backend/data/uploads_temp"
RUN_SESSION_DIR = "/home/hsuanya/workspace/running_analysis/backend/data/run_sessions"
os.makedirs(TEMP_UPLOAD_DIR, exist_ok=True)
os.makedirs(RUN_SESSION_DIR, exist_ok=True)

def move_temp_video_and_del_thumbnail(temp_video_id: str, runner_id: str, run_session_id: str, camera_index: int):
    image_path = os.path.join(TEMP_UPLOAD_DIR, temp_video_id + ".jpg")
    if os.path.exists(image_path):
        os.remove(image_path)

    # 找出所有同名檔案
    temp_video_path = glob.glob(
        os.path.join(TEMP_UPLOAD_DIR, temp_video_id + ".*")
    )[0]
    ext = os.path.splitext(temp_video_path)[1]
    
    dest_dir = os.path.join(RUN_SESSION_DIR, runner_id, run_session_id)
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, f"cam{camera_index + 1}{ext}")
    shutil.move(temp_video_path, dest_path)
    return dest_path

async def analyze_and_save(runner_id: str, run_session_id: str, camera_count: int):
    async with async_session() as session:
        try:
            folder = os.path.join(RUN_SESSION_DIR, runner_id, run_session_id)
            run_session = await session.get(RunSession, UUID(run_session_id))
            if not run_session:
                print(f"RunSession {run_session_id} not found")
                return

            run_session.status = "processing"
            run_session.progress = 0
            await session.commit()

            loop = asyncio.get_running_loop()
            def progress_callback(p):
                async def update_db():
                    async with async_session() as sess:
                        stmt = update(RunSession).where(RunSession.id == UUID(run_session_id)).values(progress=p)
                        await sess.execute(stmt)
                        await sess.commit()
                asyncio.run_coroutine_threadsafe(update_db(), loop)

            # 1️⃣ 執行分析
            raw_data = await asyncio.to_thread(track_and_draw, folder, "analyzed_video", camera_count, progress_callback)

            # 2️⃣ 將 raw_data 寫入資料庫
            analysis_meta = AnalysisMeta(
                run_session_id=UUID(run_session_id),
                total_time=raw_data.get("total_time", 0),
                avg_velocity=raw_data.get("avg_velocity", 0),
                avg_acceleration=raw_data.get("avg_acceleration", 0),
                avg_step_length=raw_data.get("avg_step_length", 0),
                summary=raw_data.get("summary", {})
            )
            session.add(analysis_meta)
            run_session = await session.get(RunSession, UUID(run_session_id)) # 重新取得以確保狀態正確
            run_session.status = "done"
            run_session.progress = 100

            await session.commit()
        except Exception as e:
            print(f"Error during analysis for session {run_session_id}: {e}")
            try:
                # 使用新的 session 或是確保目前的 session 還可用
                run_session = await session.get(RunSession, UUID(run_session_id))
                if run_session:
                    run_session.status = "failed"
                    await session.commit()
                    print(f"Set session {run_session_id} status to failed")
            except Exception as inner_e:
                print(f"Failed to set status to failed for session {run_session_id}: {inner_e}")

@router.post("/temp_video/{index}")
async def upload_video(
    index: int,
    file: UploadFile = File(...),
):
    base_id = uuid.uuid4().hex[:8]
    temp_video_id = f"{base_id}_cam{index + 1}"

    video_path = os.path.join(TEMP_UPLOAD_DIR, temp_video_id + Path(file.filename).suffix.lower())
    image_path = os.path.join(TEMP_UPLOAD_DIR, temp_video_id + ".jpg")

    # 1️⃣ 存影片
    with open(video_path, "wb") as buffer:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            buffer.write(chunk)

    # 2️⃣ 擷取第一幀
    cap = cv2.VideoCapture(video_path)
    success, frame = cap.read()
    cap.release()

    if not success:
        os.remove(video_path)
        raise HTTPException(400, "Failed to extract first frame")

    cv2.imwrite(image_path, frame)

    return {"tempVideoId": temp_video_id}


# ------------------------
# uploadAllInfo
# ------------------------
@router.post("/upload_all_info")
async def upload_all_info(
    req: UploadAllRequest,
    session: AsyncSession = Depends(get_session)
):
    # 建立 RunSession
    runSession = RunSession(
        runner_id=UUID(req.runnerId),
        date=datetime.strptime(req.date, "%Y-%m-%d %H:%M:%S"),
        fps=req.fps,
        camera_count=req.cameraCount,
        note=req.note
    )
    session.add(runSession)

    await session.commit()
    await session.refresh(runSession)

    for cameraIndex, tempVideoId in enumerate(req.tempVideoIds):
        video_stored_path = move_temp_video_and_del_thumbnail(tempVideoId, req.runnerId, str(runSession.id), cameraIndex)
        video = Video(
            run_session_id=runSession.id,
            camera_index=cameraIndex,
            video_path=video_stored_path
        )
        session.add(video)
        await session.commit()
        await session.refresh(video)    

    asyncio.create_task(analyze_and_save(req.runnerId, str(runSession.id), req.cameraCount))

    return {"runSessionId": runSession.id}


# ------------------------
# uploadSeperatelyNew
# ------------------------
@router.post("/upload_seperately_new")
async def upload_seperately_new(
    req: UploadSeperatelyNewRequest,
    session: AsyncSession = Depends(get_session)
) -> UploadSeperatelyStatus:
    # 建立 RunSession
    runSession = RunSession(
        runner_id=UUID(req.runnerId),
        date=datetime.strptime(req.date, "%Y-%m-%d %H:%M:%S"),
        fps=req.fps,
        camera_count=req.cameraCount,
        note=req.note
    )
    session.add(runSession)

    await session.commit()
    await session.refresh(runSession)


    videoStoredPath = move_temp_video_and_del_thumbnail(req.tempVideoId, req.runnerId, str(runSession.id), req.cameraIndex)
    video = Video(
        run_session_id=runSession.id,
        camera_index=req.cameraIndex,
        video_path=videoStoredPath
    )
    session.add(video)
    await session.commit()
    await session.refresh(video)

    
    # 只有 camera_count == 1 才分析
    if req.cameraCount == 1:
        asyncio.create_task(analyze_and_save(req.runnerId, str(runSession.id), req.cameraCount))
        return UploadSeperatelyStatus(
            runnerId=req.runnerId,
            runSessionId=str(runSession.id),
            isAllUploaded=True,
            unuploadedCameraIndexes=[]
        )

    unuploadedCameraIndexes = [i for i in range(req.cameraCount) if i != req.cameraIndex]
    return UploadSeperatelyStatus(
        runnerId=req.runnerId,
        runSessionId=str(runSession.id),
        isAllUploaded=False,
        unuploadedCameraIndexes=unuploadedCameraIndexes
    )

# ------------------------
# uploadSeperatelySelect
# ------------------------
@router.post("/upload_seperately_select")
async def upload_seperately_select(
    req: UploadSeperatelySelectRequest,
    session: AsyncSession = Depends(get_session)
) -> UploadSeperatelyStatus:
    stored_path = move_temp_video_and_del_thumbnail(req.tempVideoId, req.runnerId, req.runSessionId, req.cameraIndex)
    video = Video(
        run_session_id=UUID(req.runSessionId),
        camera_index=req.cameraIndex,
        video_path=stored_path
    )
    session.add(video)
    await session.commit()
    await session.refresh(video)

    # 檢查已上傳影片數量是否等於 camera_count
    # 取得 run_session
    runSession = await session.get(RunSession, UUID(req.runSessionId))

    # 🔹 撈出已上傳的 camera_index
    stmt = select(Video.camera_index).where(
        Video.run_session_id == UUID(req.runSessionId)
    )
    result = await session.execute(stmt)
    uploaded_indexes = {row[0] for row in result.all()}

    # 🔹 計算尚未上傳的
    expected_indexes = set(range(runSession.camera_count))
    unuploadedCameraIndexes = sorted(expected_indexes - uploaded_indexes)

    # 🔹 是否全部上傳完成
    isAllUploaded = len(unuploadedCameraIndexes) == 0
    if isAllUploaded:
        asyncio.create_task(analyze_and_save(req.runnerId, req.runSessionId, runSession.camera_count))

    return UploadSeperatelyStatus(
        runnerId=req.runnerId,
        runSessionId=req.runSessionId,
        isAllUploaded=isAllUploaded,
        unuploadedCameraIndexes=unuploadedCameraIndexes
    )

