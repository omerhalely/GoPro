from picamera2 import Picamera2
from picamera2.outputs import FfmpegOutput
from picamera2.encoders import H264Encoder
import cv2, psutil, threading, queue, os
from datetime import datetime
from typing import Union


frame_queue = queue.Queue(maxsize=500)

def get_available_RAM():
    mem = psutil.virtual_memory()
    total = mem.total / 1e6
    available = mem.available / 1e6
    return available, total


def writer(output_dir, output_size, fps):
    videos_path = os.path.join(output_dir, "videos")
    if not os.path.exists(videos_path):
        os.mkdir(videos_path)
    current_date_str = datetime.now().strftime("%Y-%m-%d")
    current_date_video_path = os.path.join(videos_path, current_date_str)
    if not os.path.exists(current_date_video_path):
        os.mkdir(current_date_video_path)
    current_time = datetime.now().strftime("%H-%M-%S")
    output_path = os.path.join(current_date_video_path, f"{current_time}.mp4")

    fourcc = cv2.VideoWriter_fourcc(*'H264')
    out = cv2.VideoWriter(output_path, fourcc, fps, output_size)
    
    while True:
        frame = frame_queue.get()
        if frame is None:
            break
        out.write(frame)
    
    out.release()

def get_path(output_dir: str)-> str:
    videos_path = os.path.join(output_dir, "videos")
    if not os.path.exists(videos_path):
        os.mkdir(videos_path)
    current_date_str = datetime.now().strftime("%Y-%m-%d")
    current_date_video_path = os.path.join(videos_path, current_date_str)
    if not os.path.exists(current_date_video_path):
        os.mkdir(current_date_video_path)
    current_time = datetime.now().strftime("%H-%M-%S")
    output_path = os.path.join(current_date_video_path, f"{current_time}.mp4")
    return output_path

def video_capture(
        output_dir: str,
        stop_evt: threading.Event,
        width: int,
        height: int,
        fps: int,
        bitrate: int,
        controls: Union[dict, None],
        inline_headers: bool = True
):
    output_path = get_path(output_dir)
    picam2 = None
    try:
        picam2 = Picamera2()
    except Exception:
        pass
    
    config = picam2.create_preview_configuration(
        main={
            "size": (width, height),
            "format": "RGB888"
        },
        controls={
            "FrameRate": fps
        }
    )
    picam2.configure(config)

    if controls is not None:
        picam2.set_controls(controls)

    encoder = H264Encoder(bitrate=bitrate, repeat=inline_headers)
    output = FfmpegOutput(output_path)

    try:
        picam2.start_recording(encoder, output)

        while not stop_evt.wait(timeout=0.25):
            pass

    finally:
        try:
            picam2.stop_recording()
        except Exception:
            pass
        if picam2 is not None:
            picam2.close()
