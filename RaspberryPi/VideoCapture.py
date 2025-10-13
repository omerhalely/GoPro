# from picamera2 import Picamera2
# import RPi.GPIO as GPIO
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


def writer(output_size, fps):
    output_path = os.path.join(os.getcwd(), "outputs", "output.avi")
    fourcc = cv2.VideoWriter_fourcc(*'XVID')
    out = cv2.VideoWriter(output_path, fourcc, fps, output_size)
    
    while True:
        frame = frame_queue.get()
        if frame is None:
            break
        out.write(frame)
    
    print("End Video")
    out.release()


def video_capture(stop_evt: threading.Event):
    picam2 = Picamera2()
    
    size = (int(640 // 2), int(480 // 2))
    fps = 25
    config = picam2.create_preview_configuration(
        main={
            "size": size,
            "format": "RGB888"
        },
        controls={
            "FrameRate": fps
        }
    )

    picam2.set_controls({
        "AeEnable": True,
        "ExposureTime": 8000,
        "AnalogueGain": 8.0
    })


    picam2.configure(config)
    picam2.start()

    t = threading.Thread(target=writer, args=(size, fps))
    t.start()
    prev_available, total = get_available_RAM()
    while not stop_evt.is_set():
        start = time.time()
        frame = picam2.capture_array()
        
        try:
            frame_queue.put_nowait(frame)
            current_available, total = get_available_RAM()
            delta_available = prev_available - current_available
            prev_available = current_available
            
            if current_available < 100:
                break
            
        except queue.Full:
            print("Dropped frame (queue full)")
            
        cv2.imshow("Camera", frame)
        if cv2.waitKey(1) == ord("q"):
            break
        if time.time() - start < 1 / fps:
            time.sleep(1 / fps - (time.time() - start))
        end = time.time()
        current_fps = 1 / (end - start)
        print(f"FPS : {current_fps:.2f}Hz | Queue Length : {frame_queue.qsize()} | Delta Available : {delta_available:.2f}")

    print(f"Saving {frame_queue.qsize()} frames")

    frame_queue.put(None)
    t.join()
    cv2.destroyAllWindows()
    picam2.stop()
    picam2.close()

if __name__ == "__main__":
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(18, GPIO.OUT)    
    GPIO.output(18, GPIO.LOW)
    
    video_capture(18)