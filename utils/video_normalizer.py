import os
import shutil
import subprocess
import json
import asyncio
from typing import List, Dict, Any, Tuple
import cv2
from sqlalchemy import update
from db_models import RunSession, Video

STANDARD_WIDTH = 1920
STANDARD_HEIGHT = 1080


def probe_video(video_path: str) -> Dict[str, Any]:
    """
    取得影片的真實解析度、幀率 (FPS)、時長、旋轉標籤以及是否有音訊。
    優先使用 ffprobe；若失敗則回退至 cv2.VideoCapture。
    """
    info = {
        "width": 0,
        "height": 0,
        "fps": 30.0,
        "duration": 0.0,
        "rotation": 0,
        "has_audio": False,
        "codec": "",
    }

    if not os.path.exists(video_path):
        return info

    # 1. 嘗試使用 ffprobe 取得詳細串流資訊
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate,avg_frame_rate,duration,codec_name:stream_tags=rotate:stream_side_data=rotation",
            "-of", "json", video_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=10)
        data = json.loads(res.stdout)
        streams = data.get("streams", [])
        if streams:
            s = streams[0]
            info["width"] = int(s.get("width") or 0)
            info["height"] = int(s.get("height") or 0)
            info["codec"] = s.get("codec_name", "")

            # 檢查旋轉標籤 (手機錄影常見)
            rot = 0
            tags = s.get("tags", {})
            if "rotate" in tags:
                try:
                    rot = int(float(tags["rotate"]))
                except Exception:
                    pass
            for side in s.get("side_data_list", []):
                if "rotation" in side:
                    try:
                        rot = int(float(side["rotation"]))
                    except Exception:
                        pass
            info["rotation"] = rot

            # 計算幀率
            r_fps = s.get("r_frame_rate", "30/1")
            avg_fps = s.get("avg_frame_rate", "30/1")
            fps_val = 0.0
            for rate_str in (avg_fps, r_fps):
                if rate_str and "/" in rate_str:
                    num, den = rate_str.split("/")
                    if float(den) > 0:
                        calc = float(num) / float(den)
                        if 10.0 <= calc <= 240.0:
                            fps_val = calc
                            break
            if fps_val > 0:
                info["fps"] = fps_val

            if "duration" in s:
                try:
                    info["duration"] = float(s["duration"])
                except Exception:
                    pass
    except Exception as e:
        print(f"[video_normalizer] ffprobe 讀取 {video_path} 失敗 ({e})，使用 cv2 備援")
        try:
            cap = cv2.VideoCapture(video_path)
            if cap.isOpened():
                info["width"] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                info["height"] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                cap_fps = cap.get(cv2.CAP_PROP_FPS)
                if cap_fps and 10.0 <= cap_fps <= 240.0:
                    info["fps"] = float(cap_fps)
                cap.release()
        except Exception as cv_e:
            print(f"[video_normalizer] cv2 讀取失敗: {cv_e}")

    # 2. 檢查是否有音訊串流
    try:
        cmd_a = [
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_name",
            "-of", "json", video_path
        ]
        res_a = subprocess.run(cmd_a, capture_output=True, text=True, check=True, timeout=5)
        data_a = json.loads(res_a.stdout)
        if data_a.get("streams"):
            info["has_audio"] = True
    except Exception:
        pass

    return info


def determine_target_specs(probed_list: List[Dict[str, Any]]) -> Tuple[int, int, int]:
    """
    根據所有參賽影片的硬體真實規格，決定統一標準化的目標規格：
    - 目標解析度：固定為 1920x1080 (1080p)。
    - 目標 FPS：
      - 若有任何一支影片 FPS <= 45 (常見如 24, 25, 30 FPS，包含手機 Web 錄影)，
        統一降採樣對齊至 30 FPS。
      - 若所有影片皆 >= 45 FPS (如皆為 60 FPS)，則維持以 60 FPS 作為基準。
    """
    target_width = STANDARD_WIDTH
    target_height = STANDARD_HEIGHT

    if not probed_list:
        return target_width, target_height, 60

    min_fps = min(p["fps"] for p in probed_list)
    if min_fps <= 45.0:
        target_fps = 30
    else:
        target_fps = 60

    return target_width, target_height, target_fps


def convert_to_standard(
    input_path: str,
    output_path: str,
    target_width: int,
    target_height: int,
    target_fps: int,
    has_audio: bool = False
) -> bool:
    """
    透過 FFmpeg 將影片標準化為統一的 1080p 解析度、固定幀率 (CFR)、H.264 編碼與 MP4 容器。
    優先嘗試硬體加速 (h264_nvenc)；失敗時無縫回退至 CPU (libx264)。
    """
    vf_filter = (
        f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
        f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    )

    audio_args = ["-c:a", "aac", "-b:a", "128k"] if has_audio else ["-an"]

    # 1. 嘗試 GPU (NVENC)
    cmd_nvenc = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", vf_filter,
        "-r", str(target_fps),
        "-fps_mode", "cfr",
        "-c:v", "h264_nvenc",
        "-preset", "p4",
        "-pix_fmt", "yuv420p",
        *audio_args,
        output_path
    ]

    try:
        subprocess.run(cmd_nvenc, capture_output=True, text=True, check=True)
        return True
    except Exception as e:
        print(f"[video_normalizer] GPU nvenc 轉檔失敗 ({e})，切換至 CPU libx264...")

    # 2. 回退至 CPU (libx264)
    cmd_cpu = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", vf_filter,
        "-r", str(target_fps),
        "-fps_mode", "cfr",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        *audio_args,
        output_path
    ]

    try:
        subprocess.run(cmd_cpu, capture_output=True, text=True, check=True)
        return True
    except Exception as e:
        print(f"[video_normalizer] CPU libx264 轉檔失敗: {e}")
        return False


async def normalize_session_videos(
    session,
    run_session: RunSession,
    videos: List[Video],
    folder: str,
    progress_callback=None
) -> int:
    """
    前處理管線：
    1. 探測 session 內所有影片的解析度與 FPS。
    2. 自動推論統一的目標 FPS (30 或 60) 與 1080p。
    3. 自動將規格不一致或非常規格式 (webm/mov/vfr) 的影片轉檔為標準化 MP4。
    4. 自動將資料庫中 RunSession.fps 更新為真實基準數值並持久化。
    5. 更新各 Video.video_path 指向標準化 MP4 檔案。
    回傳最終確定的基準 target_fps。
    """
    if not videos:
        return 60

    print(f"\n[video_normalizer] 開始檢查 RunSession {run_session.id} 的 {len(videos)} 支影片規格...")

    # 1. 探測每支影片
    probed_list = []
    for v in videos:
        p_info = probe_video(v.video_path)
        probed_list.append(p_info)
        print(f"  - 相機 {v.camera_index + 1}: {v.video_path} → {p_info['width']}x{p_info['height']} @ {p_info['fps']:.2f} FPS (rot: {p_info['rotation']})")

    # 2. 決定標準化目標規格
    target_w, target_h, target_fps = determine_target_specs(probed_list)
    print(f"  ▶ 系統決定統一標準規格：{target_w}x{target_h} @ {target_fps} FPS (CFR)")

    # 3. 更新資料庫中的 RunSession.fps
    if run_session.fps != target_fps:
        print(f"  ▶ 更新 RunSession.fps：原先 {run_session.fps} → 自動修正為 {target_fps}")
        run_session.fps = target_fps
        stmt = update(RunSession).where(RunSession.id == run_session.id).values(fps=target_fps)
        await session.execute(stmt)
        await session.commit()

    # 4. 逐一轉換需標準化的影片
    total_v = len(videos)
    for idx, (v, p_info) in enumerate(zip(videos, probed_list)):
        if progress_callback:
            # 預處理進度介於 1% ~ 10%
            p_val = int(1 + (idx / total_v) * 9)
            progress_callback(p_val)

        orig_ext = os.path.splitext(v.video_path)[1].lower()
        needs_convert = (
            p_info["width"] != target_w or
            p_info["height"] != target_h or
            abs(p_info["fps"] - target_fps) > 0.5 or
            p_info["rotation"] != 0 or
            orig_ext != ".mp4"
        )

        std_filename = f"cam{v.camera_index + 1}.mp4"
        std_filepath = os.path.join(folder, std_filename)

        if needs_convert:
            print(f"  ▶ 相機 {v.camera_index + 1} 需標準化轉檔 → 目標: {target_w}x{target_h} {target_fps}FPS")
            temp_out = std_filepath + ".tmp.mp4"

            # 非阻塞非同步執行 FFmpeg
            success = await asyncio.to_thread(
                convert_to_standard,
                input_path=v.video_path,
                output_path=temp_out,
                target_width=target_w,
                target_height=target_h,
                target_fps=target_fps,
                has_audio=p_info["has_audio"]
            )

            if success and os.path.exists(temp_out):
                # 若舊檔案名稱與標準名稱不同，刪除舊檔
                if os.path.abspath(v.video_path) != os.path.abspath(std_filepath) and os.path.exists(v.video_path):
                    try:
                        os.remove(v.video_path)
                    except Exception:
                        pass
                if os.path.exists(std_filepath):
                    try:
                        os.remove(std_filepath)
                    except Exception:
                        pass
                shutil.move(temp_out, std_filepath)

                # 更新資料庫路徑
                v.video_path = std_filepath
                stmt_v = update(Video).where(Video.id == v.id).values(video_path=std_filepath)
                await session.execute(stmt_v)
                await session.commit()
                print(f"  ✅ 相機 {v.camera_index + 1} 標準化完成: {std_filepath}")
            else:
                if os.path.exists(temp_out):
                    try:
                        os.remove(temp_out)
                    except Exception:
                        pass
                print(f"  ⚠️ 相機 {v.camera_index + 1} 標準化轉檔失敗，維持原始影片")
        else:
            # 規格已完全符合，確保檔案名稱為標準 camX.mp4
            if os.path.abspath(v.video_path) != os.path.abspath(std_filepath):
                shutil.move(v.video_path, std_filepath)
                v.video_path = std_filepath
                stmt_v = update(Video).where(Video.id == v.id).values(video_path=std_filepath)
                await session.execute(stmt_v)
                await session.commit()
            print(f"  ✓ 相機 {v.camera_index + 1} 規格已標準，無需轉檔")

    print("[video_normalizer] 所有影片標準化前處理完畢！\n")
    return target_fps
