#!/usr/bin/with-contenv bashio
set -euo pipefail

# catch shutdown signals and forward to both children
cleanup() {
  bashio::log.info "Signal received, stopping Python..."
  kill -TERM "$PYTHONPID" 2>/dev/null || true
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

#export BLINKA_FORCECHIP=$(bashio::config 'blinka_forcechip')
export I2C_BUS=$(bashio::config 'i2c_bus')
export PIGPIO_ADDR=$(bashio::config 'pigpio_instance')
export CHIPID=$(bashio::config 'chipid')
export BOARDID=$(bashio::config 'boardid')

bashio::log.info "Starting Python app..."
python3 -u /usr/src/jank/main.py &
PYTHONPID=$!
bashio::log.info "Python PID=${PYTHONPID}"

wait "$PYTHONPID"
cleanup