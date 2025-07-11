#!/usr/bin/with-contenv bashio
set -euo pipefail

# catch shutdown signals and forward to both children
cleanup() {
  bashio::log.info "Signal received, stopping pigpiod and Python..."
  kill -TERM "$PIGPID" "$PYTHONPID" 2>/dev/null || true
  wait "$PIGPID" 2>/dev/null || true
  wait "$PYTHONPID" 2>/dev/null || true
  bashio::log.info "Clean shutdown complete."
  exit 0
}
trap cleanup SIGTERM SIGINT

# Discover Supervisor’s Mosquitto broker
export MQTT_BROKER=$(bashio::services mqtt "host")
export MQTT_PORT=$(bashio::services mqtt "port")
export MQTT_USERNAME=$(bashio::services mqtt "username")
export MQTT_PASSWORD=$(bashio::services mqtt "password")

bashio::log.info "Starting pigpiod..."
# -g = allow GPIO via /dev/gpio*, -f = run in foreground
pigpiod -g -f &
PIGPID=$!
bashio::log.info "pigpiod PID=${PIGPID}"

bashio::log.info "Starting Python app..."
python3 -u /usr/src/my-addon/main.py &
PYTHONPID=$!
bashio::log.info "Python PID=${PYTHONPID}"

wait "$PYTHONPID"
cleanup