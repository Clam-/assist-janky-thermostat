import queue
import threading
import copy
import time

import board
import busio
from adafruit_ads1x15.ads1115 import ADS1115, P0
from adafruit_ads1x15.ads1x15 import Mode
from adafruit_ads1x15.analog_in import AnalogIn
from dual_mc33926 import motors

from threadinghelpers import SHUTDOWN_EV

def clamp(prev, value, minoffset, maxoffset):
    return max(prev-minoffset, min(value, prev+maxoffset))

class MoveThread(threading.Thread):
    def __init__(self, motorq: queue.Queue, controllerq: queue.Queue, options):
        super().__init__()
        self.motorq = motorq
        self.controllerq = controllerq
        self.target = -1
        self.moving = 0
        self.offset = 4
        self.settings = copy.deepcopy(options)
        i2c = busio.I2C(board.D1, board.D0)  # using i2c0
        self.POS = AnalogIn(ADS1115(i2c, mode=Mode.CONTINUOUS), P0)
        self.UP = self.settings["updir"]
        self.DOWN = self.UP * -1
        self.STOP = 0
    
    def run(self):
        motors.enable()
        pos = self.POS.value
        lastmove = time.monotonic()
        try:
            while not SHUTDOWN_EV.is_set():
                # check if new target
                if not self.motorq.empty():
                    try: 
                        packet = self.motorq.get(False)
                        if packet[0] == "P": self.target = packet[1]
                        elif packet[0] == "S": self.settings = packet[1]
                    except queue.Empty: pass
                    if self.target == -2: break
                # current pos
                npos = self.POS.value
                # hectic filtering (lol why am I this jank)
                if self.moving == self.UP:
                    pos = clamp(pos, npos, -(self.offset-1), self.offset)
                elif self.moving == self.DOWN:
                    pos = clamp(pos, npos, self.offset, -(self.offset-1))
                else:
                    pos = clamp(pos, npos, 5, 5)
                
                #print(self.target, round(pos), npos)
                # TODO: Have movement timeout so not just attempting to move forever... first attempt higher speed, then bail
                # seems too hard 'cuz potential changing directions I don't want to deal with it. When I change to actual motor instead of
                # linear actuator this problem will go away 'cuz hopefully stalling won't be an issue.
                self.controllerq.put(("AP", pos))
                #print(self.settings)
                if self.target != -1:
                    if (self.moving == self.UP or self.moving == self.STOP) and pos < self.target - self.settings["posmargin"]:
                        if self.moving == self.STOP and time.monotonic() - lastmove > 2: 
                            if self.moving != self.UP: motors.motor2.setSpeed(-self.settings["speed"]) # go UP
                            self.moving = self.UP
                        if self.moving == self.DOWN: lastmove = time.monotonic()
                    elif (self.moving == self.DOWN or self.moving == self.STOP) and pos > self.target + self.settings["posmargin"]:
                        if self.moving == self.STOP and time.monotonic() - lastmove > 2: 
                            if self.moving != self.DOWN: motors.motor2.setSpeed(self.settings["speed"]) # go DOWN
                            self.moving = self.DOWN
                        if self.moving == self.DOWN: lastmove = time.monotonic()
                    else: # also stop
                        if self.moving != self.STOP: motors.setSpeeds(0, 0)
                        self.moving = self.STOP
                if self.moving != 0: SHUTDOWN_EV.wait(0.02)
                else: SHUTDOWN_EV.wait(0.2)
            print("Exiting loop...")
        finally:
            # Stop the motors, even if there is an exception
            # or the user presses Ctrl+C to kill the process.
            motors.setSpeeds(0, 0)
            motors.disable()
