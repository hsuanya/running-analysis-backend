import cv2
import sys
import os

def check_video_info(video_path):
    if not os.path.exists(video_path):
        print(f"Error: File not found at {video_path}")
        return

    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        print(f"Error: Could not open video at {video_path}")
        return

    # Get video properties
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    # Check if frame_count is invalid (OpenCV often returns negative or 0 for WebM)
    if frame_count <= 0 or frame_count > 10**10:
        print("Warning: Metadata frame count invalid. Counting frames manually... (this may take a moment)")
        # Reset to start
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        actual_frames = 0
        while True:
            ret, _ = cap.read()
            if not ret:
                break
            actual_frames += 1
        frame_count = actual_frames
    
    duration = 0
    if fps > 0:
        duration = frame_count / fps

    print(f"--- Video Info ---")
    print(f"File: {video_path}")
    print(f"Resolution: {width}x{height}")
    print(f"FPS: {fps:.2f}")
    print(f"Total Frames: {frame_count}")
    print(f"Duration: {duration:.2f} seconds")

    cap.release()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python check_video_info.py <video_path>")
    else:
        check_video_info(sys.argv[1])
