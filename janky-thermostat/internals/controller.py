import time
from typing import Optional
import queue
import logging

import busio
import board
from simple_pid import PID
import adafruit_sht4x

from ..mqtt.entity import MQTTEntity, ClimateEntity
from ..mqtt.client import MQTTClient
from .motor import MoveThread
from threadinghelpers import SHUTDOWN_EV

_LOGGER = logging.getLogger(__name__)

def adj_tunings(t, index, data):
    t = list(t) # (Kp, Ki, Kd)
    t[index] = float(data)
    return t[0], t[1], t[2]

class Controller:
    def __init__(self, client:MQTTClient, options):
        self.client = client
        self.wantposition = client.register_entity(MQTTEntity("number", "wantposition", "Desired Position", on_command=self.handle_set_position, value=0))
        self.actualposition = client.register_entity(MQTTEntity("number", "actualposition", "Actual Position"))
        self.kp = client.register_entity(MQTTEntity("number", "kp", "Proportional", on_command=self.handle_set_proportional, value=1.5))
        self.ki = client.register_entity(MQTTEntity("number", "ki", "Integral", on_command=self.handle_set_integral, value=1.2))
        self.kd = client.register_entity(MQTTEntity("number", "kd", "Derivative", on_command=self.handle_set_derivative, value=1.1))
        self.ap = client.register_entity(MQTTEntity("number", "ap", "Calc'd Prop."))
        self.ai = client.register_entity(MQTTEntity("number", "ai", "Calc'd Int."))
        self.ad = client.register_entity(MQTTEntity("number", "ad", "Calc'd Deriv."))
        self.climate = ClimateEntity("climate", "Climate", on_temp_command=self.handle_set_temp, on_mode_command=self.handle_set_mode)
        client.register_entity(self.climate)
        
        self.pid = PID(self.kp.getFloat(), self.ki.getFloat(), self.kd.getFloat(), setpoint=self.climate.getFloat(),
                output_limits=(options["posmin"], options["posmax"]), 
                auto_mode=True if self.climate.mode == "auto" or self.climate.mode == "heat" else False)
        i2c = busio.I2C(board.D1, board.D0)  # using i2c0
        self.TEMP = adafruit_sht4x.SHT4x(i2c)
        self.TEMP.mode = adafruit_sht4x.Mode.NOHEAT_HIGHPRECISION # type: ignore
        # PID extra options.
        self.pid.sample_time = options["updaterate"]  # set PID update rate UPDATE_RATE
        self.pid.proportional_on_measurement = False
        self.pid.differential_on_measurement = False
        self.motorq = queue.Queue()
        self.controllerq = queue.Queue()
        self.mover = MoveThread(self.motorq, self.controllerq, options)
        self.mover.start()
        self.schedule = options["schedule"]
        self.currentsched = ""
        self.mode: str = "off"

    def handle_set_temp(self, data):
        #expect string, parse to float
        self.pid.setpoint = float(data)
    
    def handle_set_mode(self, data):
        #expect string, it should be one of "off", "heat", or "auto"
        self.mode = data
        
    def handle_set_position(self, data):
        #expect string, parse to number
        self.climate.mode = "off"
        n = float(data)
        self.wantposition.value = n
        self.motorq.put(["P", float(n)])
    
    # (Kp, Ki, Kd) expect string, parse to number
    def handle_set_proportional(self, data):
        self.pid.tunings = adj_tunings(self.pid.tunings, 0, data)
        
    def handle_set_integral(self, data):
        self.pid.tunings = adj_tunings(self.pid.tunings, 1, data)
    
    def handle_set_derivative(self, data):
        self.pid.tunings = adj_tunings(self.pid.tunings, 2, data)
    
    def fetchsched(self, currtimestamp: str) -> Optional[dict]:
        """
        Return the row whose 'schtime' is the latest time <= currtimestamp.
        Assumes:
        - self.schedule is sorted ascending by row["schtime"] as "HH:MM".
        """
        curr: Optional[dict] = None
        for row in self.schedule:
            if curr is None or currtimestamp > row["schtime"]:
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
        lastschedcheck = 0
        try:
            while not SHUTDOWN_EV.is_set():
                # process queue
                if not self.controllerq.empty():
                    try:
                        ev = self.controllerq.get_nowait()
                        if ev[0] == "AP":
                            self.actualposition.value = ev[1]
                    except queue.Empty: pass
                currentupdate = time.monotonic()
                currentschedcheck = time.monotonic()
                # measure
                temp, humidity = self.TEMP.measurements
                # Do things...
                newpos = self.pid(temp)
                if newpos is not None: newpos = round(newpos)
                if self.mode != "off" and newpos is not None:
                    self.wantposition.value = newpos # store new location
                    # move to new setpoint
                    self.motorq.put(["P", newpos])
                # Log stats...
                self.climate.current_temperature = temp
                self.climate.current_humidity = humidity
                # log PID component values:
                components = self.pid.components
                self.ap.value = components[0]
                self.ai.value = components[1]
                self.ad.value = components[2]

                SHUTDOWN_EV.wait(max(0.5 - (currentupdate-lastupdate), 0)) # sleep at most 0.5 secs... shouldn't be off the PID period by more than 0.5... probs...
                lastupdate = currentupdate
                if (currentschedcheck - lastschedcheck > 30):
                    self.checkSetSchedule()
                    lastschedcheck = currentschedcheck
        except KeyboardInterrupt:
            SHUTDOWN_EV.set()
            print("Exiting...")
        _LOGGER.info("Main thread waiting for worker to finish…")
        self.mover.join(timeout=5)
