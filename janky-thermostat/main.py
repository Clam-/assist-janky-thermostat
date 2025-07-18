# Run this at boot to continuously poll and adjust temp.
import signal
import logging
import json
import os
import sys
OPTIONS = json.load(open("/data/options.json"))

class StdoutFilter(logging.Filter):
    def filter(self, record):
        return record.levelno < logging.WARNING
root = logging.getLogger()
root.setLevel(OPTIONS["loglevel"])
# STDOUT handler for INFO and DEBUG
out_hdlr = logging.StreamHandler(sys.stdout)
out_hdlr.setLevel(logging.DEBUG)
out_hdlr.addFilter(StdoutFilter())
out_hdlr.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
# STDERR handler for WARNING and above
err_hdlr = logging.StreamHandler(sys.stderr)
err_hdlr.setLevel(logging.WARNING)
err_hdlr.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
root.addHandler(out_hdlr)
root.addHandler(err_hdlr)

from mqtt.client import MQTTClient

from internals.threadinghelpers import handle_shutdown
from internals.controller import Controller

# Read env vars set by run.sh
BROKER   = os.getenv("MQTT_BROKER", "localhost")
PORT     = int(os.getenv("MQTT_PORT", 1883))
USERNAME = os.getenv("MQTT_USERNAME") or None
PASSWORD = os.getenv("MQTT_PASSWORD") or None

CLIENT = MQTTClient(BROKER, port=PORT, username=USERNAME, password=PASSWORD)

def processTimestamps(options):
    sch = []
    for row in options["schedule"]:
        row = row.strip()
        if row:
            timestamp, temp = row.split(" ", maxsplit=1)
            timestamp = timestamp.strip()[0:5] # normalize to HH:MM if given :seconds too
            temp = float(temp.lower().replace("c", ""))
            sch.append({"timestamp": timestamp, "temp": temp})
    options["schedule"] = sch
    options["schedule"].sort(key=lambda entry: entry["timestamp"])

if __name__ == '__main__':
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT,  handle_shutdown)
    processTimestamps(OPTIONS)
    OPTIONS["updir"] = int(OPTIONS["updir"])
    control = Controller(CLIENT, OPTIONS)
    control.loop()


