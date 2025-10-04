from picamera2 import Picamera2
import cv2
import psutil
import threading
import queue
import time
import os


frame_queue = queue.Queue(maxsize=500)

def get_available_RAM():
    mem = psutil.virtual_memory()
    total = mem.total / 1e6
    available = mem.available / 1e6
    return available, total


def writer():
    output_path = os.path.join(os.getcwd(), "outputs", "output.avi")
    fourcc = cv2.VideoWriter_fourcc(*'XVID')
    out = cv2.VideoWriter(output_path, fourcc, 25, (640, 480))
    
    while True:
        frame = frame_queue.get()
        if frame is None:
            break
        out.write(frame)
    
    print("End Video")
    out.release()
    
picam2 = Picamera2()
config = picam2.create_preview_configuration(
    main={
        "size": (640, 480),
        "format": "RGB888"
    },
    controls={
        "FrameRate": 60
    }
)

picam2.set_controls({
    "AeEnable": True,
    "ExposureTime": 8000,
    "AnalogueGain": 8.0
})


picam2.configure(config)
picam2.start()

t = threading.Thread(target=writer)
t.start()

while True:
    start = time.time()
    frame = picam2.capture_array()
    
    try:
        frame_queue.put_nowait(frame)
        available, total = get_available_RAM()
        if available < 100:
            break
    except queue.Full:
        print("Dropped frame (queue full)")
        
    cv2.imshow("Camera", frame)
    if cv2.waitKey(1) == ord("q"):
        break
    end = time.time()
    fps = 1 / (end - start)
    print(f"FPS : {fps:.2f}Hz | Queue Length : {frame_queue.qsize()}")

print(f"Saving {frame_queue.qsize()} frames")

frame_queue.put(None)
t.join()
cv2.destroyAllWindows()


