import cv2
from OfflineFiltering.VideoIterator import VideoIterator
import numpy as np


def get_neighborhood(i, j, frame):
    neighbors = []
    for di in [-1, 1]:
        for dj in [-1, 1]:
            ni, nj = i + di, j + dj
            if 0 <= ni < len(frame) and 0 <= nj < len(frame[ni]):
                neighbors.append((ni, nj))
    return neighbors

def patch_similarity(patch_a, patch_b):
    return np.sum((patch_a - patch_b) ** 2)

def patch_top_k_match(current_frame, next_frame, patch_size=7, top_k=5, max_iterations=10):
    f = np.zeros((current_frame.shape[0], current_frame.shape[1], 2))
    d = np.inf * np.ones((current_frame.shape[0], current_frame.shape[1], 1), dtype=np.float32)

    for k in range(max_iterations):
        for i in range(len(current_frame)):
            for j in range(len(current_frame[i])):
                patch_a = current_frame[max(0, i - patch_size // 2):min(len(current_frame), i + patch_size // 2 + 1),
                                        max(0, j - patch_size // 2):min(len(current_frame[i]), j + patch_size // 2 + 1)]

                for neighbor in get_neighborhood(i, j, next_frame):
                    ni, nj = neighbor
                    patch_b = next_frame[max(0, ni - patch_size // 2):min(len(next_frame), ni + patch_size // 2 + 1),
                                         max(0, nj - patch_size // 2):min(len(next_frame[ni]), nj + patch_size // 2 + 1)]

                    similarity = patch_similarity(patch_a, patch_b)
                    if similarity < d[i, j]:
                        d[i, j] = similarity
                        f[i, j] = [ni, nj]
    return f, d


if __name__ == "__main__":
    import os

    parent = os.path.abspath(os.path.join(os.getcwd(), ".."))
    path = os.path.join(parent, "RaspberryPi", "outputs", "14-10-2025", "videos", "output.avi")

    iterator = VideoIterator(path)

    # prepare two frames for patch matching
    current_frame = iterator[0]
    next_frame = iterator[1]

    f, d = patch_top_k_match(current_frame, next_frame, patch_size=7, top_k=5, max_iterations=5)
    print("Computed matches for first two frames.")
    print("f shape:", f.shape, "d shape:", d.shape)

    out_file = "first_frame_gray.jpg"
    cv2.imwrite(out_file, np.clip(current_frame, 0, 255).astype(np.uint8))
    print(f"Saved {out_file}")