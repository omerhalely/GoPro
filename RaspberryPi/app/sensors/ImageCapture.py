import os
import time
from datetime import datetime
from picamera2 import Picamera2
from typing import Union
from ..core.utils import _filter_controls


def get_path(output_dir):
    images_path = os.path.join(output_dir, "images")
    if not os.path.exists(images_path):
        os.mkdir(images_path)
    current_date_str = datetime.now().strftime("%Y-%m-%d")
    current_date_image_path = os.path.join(images_path, current_date_str)
    if not os.path.exists(current_date_image_path):
        os.mkdir(current_date_image_path)
    current_time = datetime.now().strftime("%H-%M-%S")
    output_path = os.path.join(current_date_image_path, f"{current_time}.jpg")
    return output_path


def image_capture(
        output_dir: str,
        width: int,
        height: int,
        controls: Union[dict, None]
) -> str:
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
    )
    picam2.configure(config)

    if controls is not None:
        picam2.set_controls(_filter_controls(controls))

    try:
        picam2.start()
        time.sleep(0.5)
        picam2.capture_file(output_path)
        picam2.stop()
    finally:
        if picam2 is not None:
            picam2.close()
    return output_path
