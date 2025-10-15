import os
import cv2
import bm3d
import matplotlib.pyplot as plt
import numpy as np


def denoise(video_path):
    cap = cv2.VideoCapture(video_path)

    fps = cap.get(cv2.CAP_PROP_FPS)

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    size = (width, height)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")  # "mp4v" works for .mp4 on most setups
    out = cv2.VideoWriter("Filtered.mp4", fourcc, fps, size)

    count = 0
    while True:
        print(count)
        ret, frame = cap.read()

        if not ret:
            print("End Of Video")
            break
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frame = np.asarray(frame, dtype=np.float32)
        frame = (frame - np.min(frame)) / (np.max(frame) - np.min(frame))

        denoised = bm3d.bm3d(frame, sigma_psd=25 / 255)
        denoised = np.asarray(denoised * 255, dtype=np.uint8)
        denoised = cv2.cvtColor(denoised, cv2.COLOR_RGB2BGR)
        out.write(denoised)
        count += 1


if __name__ == "__main__":
    path = os.path.join(os.getcwd(), "RaspberryPi", "outputs", "14-10-2025", "videos", "output.avi")

    denoise(
        video_path=path
    )