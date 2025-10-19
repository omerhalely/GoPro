from adafruit_ina219 import INA219
import board
import busio


class INA219:
    def __init__(self, i2c):
        while not i2c.try_lock():
            pass
        addresses = i2c.scan()
        i2c.unlock()
        
        self.ina219 = None
        if addresses:
            self.ina219 = INA219(i2c)
    
    def get_status(self):
        if self.ina219:
            return True
        return False
    
    def get_voltage(self):
        if self.ina219:
            bus_voltage = self.ina.bus_voltage
            shunt_voltage = self.ina.shunt_voltage
            return bus_voltage + shunt_voltage / 1000
        return 0
    
    def get_current(self):
        if self.ina219:
            return self.ina.current
        return 0
    
    def get_power(self):
        if self.ina219:
            return self.ina.power
        return 0
    
    def __repr__(self):
        status = "Connected" if self.get_status() else "Not Connected"
        power = self.get_power()
        voltage = self.get_voltage()
        current = self.get_current()
        
        return f"Status : {status}\nPower : {power}W\nVoltage : {voltage}V\nCurrent : {current}A"
        

if __name__ == "__main__":
    i2c = busio.I2C(board.SCL, board.SDA)
    ina219 = INA219(i2c)
    
    print(ina219)
