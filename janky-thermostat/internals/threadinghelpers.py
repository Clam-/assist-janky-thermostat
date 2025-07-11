import logging
import threading

_LOGGER = logging.getLogger(__name__)
SHUTDOWN_EV = threading.Event()

def handle_shutdown(signum, frame):
    _LOGGER.info("Shutdown signal %s received. Stopping threads...", signum)
    SHUTDOWN_EV.set()