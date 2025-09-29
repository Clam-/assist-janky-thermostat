import time
from typing import Optional
import queue
import logging

from simple_pid import PID
from pigpio_sht4x import SHT4x

from mqtt import ClimateEntity, NumberEntity, MQTTClient, MQTTEntity
from .motor import MoveThread
from .threadinghelpers import SHUTDOWN_EV

_LOGGER = logging.getLogger(__name__)

def adj_tunings(t, index, data):
    t = list(t) # (Kp, Ki, Kd)
    t[index] = float(data)
    return t[0], t[1], t[2]

class Controller:
    def __init__(self, client:MQTTClient, options):
        self.client = client
        self.manualposition = client.register_entity(NumberEntity("manualposition", "Manual Position", min_value=0, max_value=30000, 
                                                                on_command=self.handle_set_position, value=0, unit="mm"))
        self.targetposition = client.register_entity(MQTTEntity("sensor", "targetposition", "Target Position", value=0, unit="mm"))
        self.actualposition = client.register_entity(MQTTEntity("sensor", "actualposition", "Actual Position", unit="mm"))
        self.kp = client.register_entity(NumberEntity("kp", "Proportional", min_value=0, max_value=64000, on_command=self.handle_set_proportional, value=1.5, unit="mm"))
        self.ki = client.register_entity(NumberEntity("ki", "Integral", min_value=0, max_value=100, on_command=self.handle_set_integral, value=1.2, unit="mm"))
        self.kd = client.register_entity(NumberEntity("kd", "Derivative", min_value=0, max_value=64000, on_command=self.handle_set_derivative, value=1.1, unit="mm"))
        self.ap = client.register_entity(MQTTEntity("sensor", "ap", "Calc'd Prop.", unit="mm"))
        self.ai = client.register_entity(MQTTEntity("sensor", "ai", "Calc'd Int.", unit="mm"))
        self.ad = client.register_entity(MQTTEntity("sensor", "ad", "Calc'd Deriv.", unit="mm"))
        self.desiredtemp = client.register_entity(MQTTEntity("sensor", "desiredtemp", "Desired Temp.", unit="°C"))
        self.actualtemp = client.register_entity(MQTTEntity("sensor", "actualtemp", "Actual Temp.", unit="°C"))
        self.actualhumid = client.register_entity(MQTTEntity("sensor", "actualhumidity", "Actual Humid.", unit="%"))
        self.climate = ClimateEntity("climate", "Climate", on_temp_command=self.handle_set_temp, on_mode_command=self.handle_set_mode)
        client.register_entity(self.climate)
        
        self.pid = PID(self.kp.getFloat(), self.ki.getFloat(), self.kd.getFloat(), setpoint=self.climate.getFloat(),
                output_limits=(options["posmin"], options["posmax"]), 
                auto_mode=True if self.climate.mode == "auto" or self.climate.mode == "heat" else False)
        self.TEMP = SHT4x()
        # PID extra options.
        self.pid.sample_time = options["updaterate"]  # set PID update rate UPDATE_RATE
        self.pid.proportional_on_measurement = False
        self.pid.differential_on_measurement = False
        self.motorq = queue.Queue()
        self.controllerq = queue.Queue()
        self.mover = MoveThread(self.motorq, self.controllerq, options)
        self.mover.start()
        self.schedule = options["schedule"]
        self.lograte = options["lograte"]
        self.currentsched = ""
        self.mode: str = "off"

    def handle_set_temp(self, data):
        #expect json parsed data
        self.pid.setpoint = data
        self.climate.value = data
        self.desiredtemp.value = data
    
    def handle_set_mode(self, data):
        #expect string, it should be one of "off", "heat", or "auto"
        self.mode = data
        if self.mode in ["heat", "auto"]:
            self.pid.auto_mode = True
        else:
            self.pid.auto_mode = False
        self.climate.mode = data
        
    def handle_set_position(self, data):
        #expect json parsed data
        if data > 0:
            self.climate.mode = "off"
            self.mode = "off"
            self.targetposition.value = data
            self.motorq.put(["P", data])
    
    # (Kp, Ki, Kd) expect json parsed data
    def handle_set_proportional(self, data):
        self.pid.tunings = adj_tunings(self.pid.tunings, 0, data)
        self.kp.value = data
        
    def handle_set_integral(self, data):
        self.pid.tunings = adj_tunings(self.pid.tunings, 1, data)
        self.ki.value = data
    
    def handle_set_derivative(self, data):
        self.pid.tunings = adj_tunings(self.pid.tunings, 2, data)
        self.kd.value = data
    
    def fetchsched(self, currtimestamp: str) -> Optional[dict]:
        """
        Return the row whose 'timestamp' is the latest time <= currtimestamp.
        Assumes:
        - self.schedule is sorted ascending by row["timestamp"] as "HH:MM".
        """
        curr: Optional[dict] = None
        for row in self.schedule:
            if currtimestamp > row["timestamp"]:
                curr = row
        if curr is None and self.schedule:
            # wrap to last entry of previous day if no pick.
            curr = self.schedule[-1]
        return curr

    def checkSetSchedule(self):
        currstamp = time.strftime("%H:%M")
        sched = self.fetchsched(currstamp)
        if sched:
            if sched["timestamp"] != self.currentsched:
                self.pid.setpoint = sched["temp"]
                self.climate.value = sched["temp"]
                self.currentsched = sched["timestamp"]

    def loop(self):
        self.client.connect()
        lastupdate = time.monotonic()
        lastschedcheck = lastupdate
        apos: int | None = None
        try:
            while not SHUTDOWN_EV.is_set():
                # process queue
                if not self.controllerq.empty():
                    try:
                        ev = self.controllerq.get_nowait()
                        size = 1
                        while ev:
                            if ev[0] == "AP":
                                apos = ev[1]
                            size+=1
                            ev = self.controllerq.get_nowait()
                        print(f"q size: {size}")
                    except queue.Empty: pass
                currentupdate = time.monotonic()
                currentschedcheck = time.monotonic()
                # measure
                temp, humidity = self.TEMP.measurements
                temp = round(temp, 2)
                humidity = round(humidity, 2)
                # Do things...
                newpos = self.pid(temp)
                if newpos is not None: newpos = round(newpos)
                if self.mode != "off" and newpos is not None:
                    self.targetposition.value = newpos # store new location
                    # move to new setpoint
                    self.motorq.put(["P", newpos])
                SHUTDOWN_EV.wait(max(0.5 - (currentupdate-lastupdate), 0)) # sleep at most 0.5 secs... shouldn't be off the PID period by more than 0.5... probs...
                lastupdate = currentupdate
                if (currentschedcheck - lastschedcheck > self.lograte):
                    # Log stats...
                    self.climate.current_temperature = temp
                    self.climate.current_humidity = humidity
                    self.actualtemp.value = temp
                    self.actualhumid.value = humidity
                    if apos is not None: 
                        self.actualposition.value = apos
                        apos = None
                    # log PID component values:
                    components = self.pid.components
                    self.ap.value = components[0]
                    self.ai.value = components[1]
                    self.ad.value = components[2]
                    self.checkSetSchedule()
                    lastschedcheck = currentschedcheck
        except KeyboardInterrupt:
            SHUTDOWN_EV.set()
            _LOGGER.info("Keyboard interrupt, exiting...")
        _LOGGER.info("Main thread waiting for worker to finish...")
        self.mover.join(timeout=5)
