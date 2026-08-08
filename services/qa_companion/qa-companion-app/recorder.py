import time
import cv2
import numpy as np
import subprocess
import shutil
import os
import threading
from collections import deque

class ShadowplayRecorder(threading.Thread):
    def __init__(self, fps=10, buffer_seconds=15):
        super().__init__(daemon=True)
        self.fps = fps
        self.buffer_seconds = buffer_seconds
        self.max_frames = fps * buffer_seconds
        
        self.frames_buffer = deque(maxlen=self.max_frames)
        self.running = True
        self.saving = False
        
        self.has_ffmpeg = shutil.which("ffmpeg") is not None

    def run(self):
        frame_time = 1.0 / self.fps
        
        use_gnome_screenshot = False
        if shutil.which("gnome-screenshot"):
            use_gnome_screenshot = True
            print("Using native gnome-screenshot fallback for Wayland")
        elif shutil.which("grim"):
            use_gnome_screenshot = "grim"
            print("Using grim fallback for Wayland")

        while self.running:
            start_time = time.time()

            if not self.saving:
                try:
                    img = None
                    if use_gnome_screenshot == "grim":
                        import tempfile
                        tmp_path = tempfile.mktemp(suffix=".png")
                        subprocess.run(["grim", "-l", "1", tmp_path], capture_output=True)
                        raw = cv2.imread(tmp_path)
                        if raw is not None: img = raw
                        if os.path.exists(tmp_path): os.remove(tmp_path)
                    elif use_gnome_screenshot == True:
                        import tempfile
                        tmp_path = tempfile.mktemp(suffix=".png")
                        subprocess.run(["gnome-screenshot", "-f", tmp_path], capture_output=True)
                        raw = cv2.imread(tmp_path)
                        if raw is not None: img = raw
                        if os.path.exists(tmp_path): os.remove(tmp_path)

                    if img is not None:
                        height, width = img.shape[:2]
                        if width > 1920:
                            scale = 1920 / width
                            img = cv2.resize(img, (int(width * scale), int(height * scale)))
                            
                        height, width = img.shape[:2]
                        if width % 2 != 0: width -= 1
                        if height % 2 != 0: height -= 1
                        img = cv2.resize(img, (width, height))
                            
                        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 65]
                        _, jpeg_encoded = cv2.imencode('.jpg', img, encode_param)
                        self.frames_buffer.append(jpeg_encoded)
                        
                except Exception as e:
                    pass

            elapsed = time.time() - start_time
            sleep_time = max(0, frame_time - elapsed)
            time.sleep(sleep_time)

    def save_replay(self, filepath="replay.mp4"):
        if not self.frames_buffer:
            print("Buffer is empty!")
            return None

        self.saving = True
        print(f"Saving replay to {filepath}...")
        
        first_frame = cv2.imdecode(self.frames_buffer[0], cv2.IMREAD_COLOR)
        if first_frame is None:
            self.saving = False
            return None
            
        height, width, _ = first_frame.shape
        temp_filepath = filepath.replace(".mp4", "_temp.avi")
        
        fourcc = cv2.VideoWriter_fourcc(*'MJPG')
        out = cv2.VideoWriter(temp_filepath, fourcc, self.fps, (width, height))

        frame_count = 0
        for jpeg_encode in list(self.frames_buffer):
            frame = cv2.imdecode(jpeg_encode, cv2.IMREAD_COLOR)
            if frame is not None:
                out.write(frame)
                frame_count += 1

        out.release()
        
        final_filepath = filepath
        if self.has_ffmpeg:
            print("Optimizing video to H.264 MP4 via FFMPEG...")
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", temp_filepath, "-c:v", "libx264", "-preset", "fast", "-crf", "28", "-pix_fmt", "yuv420p", filepath],
                    capture_output=True, check=True
                )
                if os.path.exists(temp_filepath): os.remove(temp_filepath)
            except Exception as e:
                print(f"FFMPEG conversion failed: {e}. Falling back to WebM.")
                subprocess.run(["ffmpeg", "-y", "-i", temp_filepath, "-c:v", "libvpx", "-b:v", "1M", filepath.replace(".mp4", ".webm")], capture_output=True)
                final_filepath = filepath.replace(".mp4", ".webm")
        else:
            final_filepath = temp_filepath

        self.saving = False
        print(f"Saved {frame_count} frames ({frame_count/self.fps:.1f} seconds).")
        return final_filepath

    def stop(self):
        self.running = False
