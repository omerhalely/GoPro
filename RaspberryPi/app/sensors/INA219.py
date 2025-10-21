from adafruit_ina219 import INA219, ADCResolution, BusVoltageRange, Gain
import board
import busio


class ina219:
    def __init__(self, i2c):
        while not i2c.try_lock():
            pass
        addresses = i2c.scan()
        i2c.unlock()
        
        self.ina219 = None
        if addresses:
            self.ina219 = INA219(i2c)
        self.config()
    
    def config(self):
        if self.ina219:
            self.ina219.bus_voltage_range = BusVoltageRange.RANGE_32V
            self.ina219.gain = Gain.DIV_8_320MV
            self.ina219.bus_adc_resolution = ADCResolution.ADCRES_12BIT_128S
            self.ina219.shunt_adc_resolution = ADCResolution.ADCRES_12BIT_128S
            self.ina219.set_calibration_32V_2A()
            
    def get_status(self):
        if self.ina219:
            return True
        return False
    
    def get_voltage(self):
        if self.ina219:
            bus_voltage = self.ina219.bus_voltage
            shunt_voltage = self.ina219.shunt_voltage
            return bus_voltage + shunt_voltage / 1000
        return 0
    
    def get_current(self):
        if self.ina219:
            return self.ina219.current
        return 0
    
    def get_power(self):
        if self.ina219:
            return self.ina219.power
        return 0
    
    def __repr__(self):
        status = "Connected" if self.get_status() else "Not Connected"
        power = self.get_power()
        voltage = self.get_voltage()
        current = self.get_current()
        
        return f"Status : {status}\nPower : {power}W\nVoltage : {voltage}V\nCurrent : {current}A"
        

if __name__ == "__main__":
    i2c = busio.I2C(board.SCL, board.SDA)
    ina = ina219(i2c)
    
    calibration_length = 100
    P = []
    V = []
    I = []
    for i in range(calibration_length):
        power = ina.get_power()
        voltage = ina.get_voltage()
        current = ina.get_current()
        
        P.append(power)
        V.append(voltage)
        I.append(current)
    
    print(f"Mean Power : {sum(P) / len(P)}")
    print(f"Mean Voltage : {sum(V) / len(V)}")
    print(f"Mean Current : {sum(I) / len(I)}")
