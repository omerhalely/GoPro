import cv2


class VideoIterator:
    def __init__(self, path):
        self.path = path

        self.frames = self.load_frames()

    def load_frames(self):
        # Placeholder for loading video frames from the given path
        frames = []
        cap = cv2.VideoCapture(self.path)
        for i in range(int(cap.get(cv2.CAP_PROP_FRAME_COUNT))):
            ret, frame = cap.read()
            if not ret:
                break
            frames.append(frame)
        cap.release()
        return frames

    def __len__(self):
        return len(self.frames)

    def __getitem__(self, index):
        return self.frames[index]


if __name__ == "__main__":
    import os

    parent = os.path.abspath(os.path.join(os.getcwd(), ".."))
    path = os.path.join(parent, "RaspberryPi", "outputs", "14-10-2025", "videos", "output.avi")

    iterator = VideoIterator(path)
    print(f"Loaded {len(iterator)} frames from {path}")

    for i, frame in enumerate(iterator):
        if i >= 5:
            break
        print(f"Frame {i}: shape={frame.shape}, dtype={frame.dtype}")