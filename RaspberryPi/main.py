import time
import RPi.GPIO as GPIO

from VideoCapture import video_capture


GPIO.setwarnings(False)


def main():
    GPIO.setmode(GPIO.BCM)

    gpio_pins = {
        "power_off_pin" : 16,
        "video_capture_pin" : 17,
        "video_stop_pin" : 18
    }
    
    for pin in gpio_pins:
        GPIO.setup(gpio_pins[pin], GPIO.OUT)    
        GPIO.output(gpio_pins[pin], GPIO.LOW)

    power_off_state = GPIO.input(gpio_pins["power_off_pin"])
    video_capture_state = GPIO.input(gpio_pins["video_capture_pin"])
    
    print("Ready")
    while not power_off_state:
        if video_capture_state:
            video_capture(gpio_pins["video_stop_pin"])
            GPIO.output(gpio_pins["video_capture_pin"], GPIO.LOW)
            GPIO.output(gpio_pins["video_stop_pin"], GPIO.LOW)
        
        power_off_state = GPIO.input(gpio_pins["power_off_pin"])
        video_capture_state = GPIO.input(gpio_pins["video_capture_pin"])
        
        time.sleep(1)
        
    GPIO.output(gpio_pins["video_capture_pin"], GPIO.LOW)
    print("DONE")


if __name__ == "__main__":
    main()