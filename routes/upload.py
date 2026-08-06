import os, shutil, uuid, asyncio, glob, json
from uuid import UUID
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from db.session import get_session, async_session
from db_models import RunSession, AnalysisMeta, Video
import sys
pipeline_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "runner-analysis-pipeline"))
if pipeline_dir not in sys.path:
    sys.path.insert(0, pipeline_dir)
from analyze import run_analysis
from datetime import datetime
import pandas as pd
import cv2
from pathlib import Path
from response_chemas import UploadSeperatelyStatus, UploadSeperatelyNewRequest, UploadSeperatelySelectRequest, UploadAllRequest

router = APIRouter()

TEMP_UPLOAD_DIR = "/home/hsuanya/workspace/running_analysis/backend/data/uploads_temp"
RUN_SESSION_DIR = "/home/hsuanya/workspace/running_analysis/backend/data/run_sessions"
os.makedirs(TEMP_UPLOAD_DIR, exist_ok=True)
os.makedirs(RUN_SESSION_DIR, exist_ok=True)

# --- CONFIG ---
# 是否在分析失敗時使用假資料 (True: 開啟居家測試模式, False: 關閉)
ENABLE_MOCK_ON_FAILURE = False

def move_temp_video_and_del_thumbnail(temp_video_id: str, runner_id: str, run_session_id: str, camera_index: int):
    image_path = os.path.join(TEMP_UPLOAD_DIR, temp_video_id + ".jpg")
    if os.path.exists(image_path):
        os.remove(image_path)

    matches = glob.glob(
        os.path.join(TEMP_UPLOAD_DIR, temp_video_id + "*")
    )
    # 排除 .jpg (縮圖)
    matches = [f for f in matches if not f.endswith(".jpg")]

    if not matches:
        raise HTTPException(404, f"Temperature video file not found for ID: {temp_video_id}")
        
    temp_video_path = matches[0]
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

            # 1️⃣ 準備 metadata.json (包含所有相機的錨點)
            stmt = select(Video).where(Video.run_session_id == UUID(run_session_id))
            result = await session.execute(stmt)
            videos = result.scalars().all()
            
            config_dict = {
                "cameras": [],
                "auto_crop": True,
                "tracking_mode": "two_pass",
                "prescan_enabled": True,
                "prescan_engine_path": os.path.join(pipeline_dir, "models", "yolo26x_ultralytics_int8.engine"),
            }
            videos_sorted = sorted(videos, key=lambda x: x.camera_index)
            meta_data_cameras = []
            
            import cv2
            for v in videos_sorted:
                anchors = json.loads(v.anchors) if v.anchors else None
                cam_cfg = {"video_path": v.video_path}
                if anchors and len(anchors) == 4:
                    cap = cv2.VideoCapture(v.video_path)
                    if cap.isOpened():
                        w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                        h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                        cap.release()
                        
                        if w > 0 and h > 0:
                            cam_cfg["start_line"] = [
                                [int(anchors[0]["x"] * w), int(anchors[0]["y"] * h)],
                                [int(anchors[3]["x"] * w), int(anchors[3]["y"] * h)]
                            ]
                            cam_cfg["end_line"] = [
                                [int(anchors[1]["x"] * w), int(anchors[1]["y"] * h)],
                                [int(anchors[2]["x"] * w), int(anchors[2]["y"] * h)]
                            ]
                        else:
                            # Fallback if invalid dimensions
                            cam_cfg["start_line"] = [[anchors[0]["x"], anchors[0]["y"]], [anchors[1]["x"], anchors[1]["y"]]]
                            cam_cfg["end_line"] = [[anchors[2]["x"], anchors[2]["y"]], [anchors[3]["x"], anchors[3]["y"]]]
                    else:
                        cam_cfg["start_line"] = [[anchors[0]["x"], anchors[0]["y"]], [anchors[1]["x"], anchors[1]["y"]]]
                        cam_cfg["end_line"] = [[anchors[2]["x"], anchors[2]["y"]], [anchors[3]["x"], anchors[3]["y"]]]
                        
                if v.top_distance_m is not None:
                    cam_cfg["distance_m"] = v.top_distance_m
                config_dict["cameras"].append(cam_cfg)
                
                meta_data_cameras.append({
                    "camera_index": v.camera_index,
                    "anchors": anchors,
                    "top_distance_m": v.top_distance_m,
                    "bottom_distance_m": v.bottom_distance_m,
                })
            
            meta_data = {
                "run_session_id": run_session_id,
                "camera_count": camera_count,
                "cameras": meta_data_cameras
            }
            
            with open(os.path.join(folder, "metadata.json"), "w") as f:
                json.dump(meta_data, f, indent=4)

            # 2️⃣ 執行分析
            raw_data = await asyncio.to_thread(
                run_analysis,
                config_dict=config_dict,
                gpu="0",
                only_2d=False,
                skip_track=False,
                output_dest=folder,
                progress_callback=progress_callback
            )

            metrics_csv = raw_data.get("metrics_csv") if raw_data else None
            total_time = raw_data.get("total_time") if raw_data else None
            avg_velocity = raw_data.get("avg_velocity") if raw_data else None
            avg_acceleration = raw_data.get("avg_acceleration") if raw_data else None
            avg_step_length = raw_data.get("avg_step_length") if raw_data else None

            # 2️⃣ 將 raw_data 寫入資料庫
            analysis_meta = AnalysisMeta(
                run_session_id=UUID(run_session_id),
                total_time=total_time,
                avg_velocity=avg_velocity,
                avg_acceleration=avg_acceleration,
                avg_step_length=avg_step_length,
                summary={
                    "metrics_csv": raw_data.get("metrics_csv") if raw_data else None,
                    "angles_csv": raw_data.get("angles_csv") if raw_data else None,
                    "uncropped_video": raw_data.get("uncropped_video") if raw_data else None
                }
            )
            session.add(analysis_meta)
            run_session = await session.get(RunSession, UUID(run_session_id)) # 重新取得以確保狀態正確
            run_session.status = "done"
            run_session.progress = 100

            await session.commit()
        except Exception as e:
            print(f"Error during analysis for session {run_session_id}: {e}")
            
            # --- Mock Data Fallback ---
            if ENABLE_MOCK_ON_FAILURE:
                # 為了測試流程，當分析失敗時，我們寫入假資料並標記為完成
                print(f"Falling back to mock data for session {run_session_id}")
                try:
                    analysis_meta = AnalysisMeta(
                        run_session_id=UUID(run_session_id),
                        total_time=10.0,
                        avg_velocity=5.0,
                        avg_acceleration=0.5,
                        avg_step_length=1.2,
                        summary={"mock": "True", "error": str(e)}
                    )
                    session.add(analysis_meta)
                    
                    run_session = await session.get(RunSession, UUID(run_session_id))
                    if run_session:
                        run_session.status = "done"
                        run_session.progress = 100
                        await session.commit()
                        print(f"Set session {run_session_id} status to done (Mock Data)")
                except Exception as inner_e:
                    print(f"Failed to use mock data for session {run_session_id}: {inner_e}")
            else:
                # 正常失敗處理邏輯
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

    for cameraIndex, info in enumerate(req.videos):
        tempVideoId = info.tempVideoId
        video_stored_path = move_temp_video_and_del_thumbnail(tempVideoId, req.runnerId, str(runSession.id), cameraIndex)
        
        # 處理錨點資料
        anchors_json = None
        top_d = None
        bot_d = None
        if info.anchors:
            anchors_json = json.dumps([p.dict() for p in info.anchors.points])
            top_d = info.anchors.topDistanceM
            bot_d = info.anchors.bottomDistanceM

        video = Video(
            run_session_id=runSession.id,
            camera_index=cameraIndex,
            video_path=video_stored_path,
            anchors=anchors_json,
            top_distance_m=top_d,
            bottom_distance_m=bot_d
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
    
    # 處理錨點
    anchors_json = None
    top_d = None
    bot_d = None
    if req.anchors:
        anchors_json = json.dumps([p.dict() for p in req.anchors.points])
        top_d = req.anchors.topDistanceM
        bot_d = req.anchors.bottomDistanceM

    video = Video(
        run_session_id=runSession.id,
        camera_index=req.cameraIndex,
        video_path=videoStoredPath,
        anchors=anchors_json,
        top_distance_m=top_d,
        bottom_distance_m=bot_d
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
    
    # 處理錨點
    anchors_json = None
    top_d = None
    bot_d = None
    if req.anchors:
        anchors_json = json.dumps([p.dict() for p in req.anchors.points])
        top_d = req.anchors.topDistanceM
        bot_d = req.anchors.bottomDistanceM

    video = Video(
        run_session_id=UUID(req.runSessionId),
        camera_index=req.cameraIndex,
        video_path=stored_path,
        anchors=anchors_json,
        top_distance_m=top_d,
        bottom_distance_m=bot_d
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

