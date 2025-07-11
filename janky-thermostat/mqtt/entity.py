from .device import MQTTDevice

from threading import Lock
from typing import List, Optional, Callable, Union, Dict, Any
import paho.mqtt.client as mqtt
import json
import logging

_LOGGER = logging.getLogger(__name__)

class MQTTEntity:
    def __init__(self,
                 domain: str,
                 object_id: str,
                 name: str,
                 state_topic: str = "",
                 command_topic: str = "",
                 unit: Optional[str] = None,
                 device_class: Optional[str] = None,
                 retain: bool = True,
                 value: Optional[Union[str, float]] = None,
                 on_command: Optional[Callable[[Union[str, float, dict]], None]] = None) -> None:
        self.domain: str = domain
        self.object_id: str = object_id
        self.name: str = name
        self.unit: Optional[str] = unit
        self.device_class: Optional[str] = device_class
        self.retain: bool = retain

        self._value_lock: Lock = Lock()
        self._value: Optional[Union[str, float]] = value
        self.client: Optional[mqtt.Client] = None
        self.state_topic: str = state_topic
        self.command_topic: str = command_topic
        # Optional command handler
        self._on_command: Optional[Callable[[Union[str, float, dict]], None]] = on_command

    @property
    def value(self) -> Optional[Union[str, float]]:
        with self._value_lock:
            return self._value

    @value.setter
    def value(self, new_value: Union[str, float]) -> None:
        with self._value_lock:
            if new_value == self._value:
                return
            self._value = new_value
        if self.client:
            payload: str = json.dumps(new_value) if not isinstance(new_value, str) else new_value
            self.client.publish(self.state_topic, payload=payload, retain=self.retain)
            _LOGGER.debug("Published %s ← %s", self.state_topic, payload)
        else:
            _LOGGER.warning("MQTT client not set for entity '%s'; publish skipped", self.object_id)
    def getFloat(self) -> float:
        return 0 if self.value is None else float(self.value)
    
    def build_topics(self, device: MQTTDevice) -> str:
        device_id = device.identifiers[0]
        prefix_id  = device_id if device_id else self.object_id
        base_prefix= f"{self.domain}/{prefix_id}/{self.object_id}"
        if self.state_topic == "":
            self.state_topic = f"{base_prefix}/state"
        if self.command_topic == "":
            self.command_topic = f"{base_prefix}/set"
        return prefix_id

    def discovery_topic(self) -> str:
        return f"homeassistant/{self.domain}/{self.object_id}/config"

    def discovery_payload(self, device) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "name": self.name,
            "unique_id": self.object_id,
            "state_topic": self.state_topic,
            "device": json.dumps(device)
        }
        if self._on_command:
            payload["command_topic"] = self.command_topic
        if self.unit:
            payload["unit_of_measurement"] = self.unit
        if self.device_class:
            payload["device_class"] = self.device_class
        return payload

    def on_command(self, payload: Union[str, float, dict]) -> None:
        """
        Default command handler. Override in subclass or assign via constructor.
        """
        if self._on_command:
            try:
                self._on_command(payload)
            except Exception:
                _LOGGER.exception("Error in entity-level on_command callback")
        else:
            _LOGGER.debug("Command received for %s but no handler defined", self.object_id)


class ClimateEntity(MQTTEntity):
    def __init__(self,
                 object_id: str,
                 name: str,
                 target_temp_state: str = "",
                 target_temp_command: str = "",
                 current_temp_topic: str = "",
                 current_humidity_topic: str = "",
                 mode_state: str = "",
                 mode_command: str = "",
                 step: float = 0.1,
                 modes: Optional[List[str]] = ["off", "auto", "heat"],
                 unit: str = "°C",
                 retain: bool = True,
                 value: Optional[Union[str, float]] = 0.0,
                 on_temp_command: Optional[Callable[[Union[str, float, dict]], None]] = None,
                 on_mode_command: Optional[Callable[[str], None]] = None) -> None:

        super().__init__(
            domain="climate",
            object_id=object_id,
            name=name,
            state_topic=target_temp_state, # base state_topic is for the target_temp
            command_topic=target_temp_command,
            unit=unit,
            device_class=None,
            retain=retain,
            value=value,
            on_command=on_temp_command
        )

        # Climate-specific extras
        self.current_temp_topic: str = current_temp_topic
        self.step: float = step

        self.mode_state_topic: str = mode_state
        self.mode_command_topic: str = mode_command
        self.modes: List[str] = modes or []

        self._mode_lock: Lock = Lock()
        self._temp_lock: Lock = Lock()
        self._current_temperature: Optional[Union[str, float]] = None
        self._mode: Optional[str] = "off"
        self._on_mode_command: Optional[Callable[[str], None]] = on_mode_command

        self.current_humidity_topic: str = current_humidity_topic
        self._humidity_lock: Lock = Lock()
        self._current_humidity: Optional[Union[str, float]] = None

    def build_topics(self, device: MQTTDevice) -> str:
        prefix_id = super().build_topics(device)
        base_prefix= f"{self.domain}/{prefix_id}/{self.object_id}"
        if self.current_temp_topic == "":
            self.current_temp_topic = f"{base_prefix}/current_temperature"
        if self.mode_state == "":
            self.mode_state = f"{base_prefix}/mode/state"
        if self.mode_command == "":
            self.mode_command = f"{base_prefix}/mode/set"
        if self.current_humidity_topic == "":
            self.current_humidity_topic = f"{base_prefix}/current_humidity"
        return prefix_id

    @property
    def current_temperature(self) -> Optional[Union[str, float]]:
        with self._temp_lock:
            return self._current_temperature

    @current_temperature.setter
    def current_temperature(self, value: Union[str, float]) -> None:
        with self._temp_lock: 
            self._current_temperature = value
        payload: str = json.dumps(value) if not isinstance(value, str) else value
        if self.client: self.client.publish(self.current_temp_topic, payload, retain=self.retain)
        _LOGGER.debug("Published current temp (%s)", payload)

    @property
    def mode(self) -> Optional[str]:
        with self._temp_lock: 
            return self._mode

    @mode.setter
    def mode(self, value: str) -> None:
        if value in self.modes:
            with self._temp_lock:
                self._mode = value
            if self.client and self.mode_state_topic is not None:
                self.client.publish(self.mode_state_topic, value, retain=self.retain)
                _LOGGER.debug("Published HVAC mode (%s)", value)
        else:
            _LOGGER.warning("Attempted to set unsupported mode: %s", value)

    @property
    def current_humidity(self) -> Optional[Union[str, float]]:
        with self._humidity_lock:
            return self._current_humidity

    @current_humidity.setter
    def current_humidity(self, value: Union[str, float]) -> None:
        with self._humidity_lock:
            self._current_humidity = value

        if self.client:
            payload = json.dumps(value) if not isinstance(value, str) else value
            self.client.publish(self.current_humidity_topic, payload, retain=self.retain)
            _LOGGER.debug("Published current humidity (%s)", payload)

    def handle_mode_command(self, payload: str) -> None:
        """Called externally when a mode command is received."""
        if payload in self.modes:
            self.mode = payload
            if self._on_mode_command:
                try:
                    self._on_mode_command(payload)
                except Exception:
                    _LOGGER.exception("Error in mode command handler")
        else:
            _LOGGER.warning("Received unsupported mode via command_topic: %s", payload)

    def discovery_payload(self, device) -> Dict[str, Any]:
        payload: Dict[str, Any] = super().discovery_payload(device)
        payload.update({
            "current_temperature_topic": self.current_temp_topic,
            "temp_step": self.step,
        })
        if self.mode_state_topic and self.mode_command_topic:
            payload["mode_state_topic"] = self.mode_state_topic
            payload["mode_command_topic"] = self.mode_command_topic
            payload["modes"] = self.modes
        return payload