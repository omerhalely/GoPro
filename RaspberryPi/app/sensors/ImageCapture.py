import os
from datetime import datetime
from picamera2 import Picamera2


def image_capture(output_dir: str) -> str:
    images_path = os.path.join(output_dir, "images")
    if not os.path.exists(images_path):
        os.mkdir(images_path)
    current_date_str = datetime.now().strftime("%Y-%m-%d")
    current_date_image_path = os.path.join(images_path, current_date_str)
    if not os.path.exists(current_date_image_path):
        os.mkdir(current_date_image_path)
    current_time = datetime.now().strftime("%H-%M-%S")
    output_path = os.path.join(current_date_image_path, f"{current_time}.avi")
    return output_path
