# Run this at boot to continuously poll and adjust temp.
import signal
import threading
import logging
import sqlite3
import threading
import json
import os

from mqtt.client import MQTTClient

from .internals.threadinghelpers import handle_shutdown
from .internals.controller import Controller

_LOGGER = logging.getLogger(__name__)
OPTIONS = json.load(open("/data/options.json"))
# Read env vars set by run.sh
BROKER   = os.getenv("MQTT_BROKER", "localhost")
PORT     = int(os.getenv("MQTT_PORT", 1883))
USERNAME = os.getenv("MQTT_USERNAME") or None
PASSWORD = os.getenv("MQTT_PASSWORD") or None

CLIENT = MQTTClient(BROKER, port=PORT, username=USERNAME, password=PASSWORD)

def processTimestamps(options):
    for row in options["schedule"]:
        row["timestamp"] = row["timestamp"][0:5] # normalize to HH:MM if given :seconds too
    options["schedule"].sort(key=lambda entry: entry["timestamp"])

if __name__ == '__main__':
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT,  handle_shutdown)
    processTimestamps(OPTIONS)
    control = Controller(CLIENT, OPTIONS)
    control.loop()


