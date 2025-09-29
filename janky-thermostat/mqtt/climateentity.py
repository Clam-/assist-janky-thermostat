import json
import threading
from typing import Any, Callable, Dict, List, Optional, Union
import logging

import paho.mqtt.client as mqtt

from .entity import MQTTEntity
from .device import MQTTDevice

_LOGGER = logging.getLogger(__name__)

class ClimateEntity(MQTTEntity):
    def __init__(self,
                 object_id: str,
                 name: str,
                 step: float = 0.1,
                 modes: Optional[List[str]] = ["off", "auto", "heat"],
                 unit: str = "°C",
                 retain: bool = True,
                 value: Optional[Union[str, float]] = 0.0,
                 on_temp_command: Optional[Callable[[Union[str, float, dict]], None]] = None,
                 on_mode_command: Optional[Callable[[str], None]] = None,
                 max_temp: float = 30.0,
                 min_temp: float = 15.0
        ) -> None:

        super().__init__(
            domain="climate",
            object_id=object_id,
            name=name,
            unit=unit,
            device_class=None,
            retain=retain,
            value=value,
            on_command=on_temp_command
        )

        # Climate-specific extras
        self.step: float = step
        self.modes: List[str] = modes or []
        self._mode_lock: threading.Lock = threading.Lock()
        self._temp_lock: threading.Lock = threading.Lock()
        self._current_temperature: Optional[Union[str, float]] = None
        self._mode: Optional[str] = "off"
        self._on_mode_command: Optional[Callable[[str], None]] = on_mode_command
        self._humidity_lock: threading.Lock = threading.Lock()
        self._current_humidity: Optional[Union[str, float]] = None
        self._init_mode_timer: threading.Timer | None = None
        self.max_temp = max_temp
        self.min_temp = min_temp

    def _on_connect(self, client: mqtt.Client):
        super()._on_connect(client)
        if self._on_mode_command:
            # subscribe to own state topic so can get old value
            client.subscribe(self.mode_state_topic, qos=0)
            client.message_callback_add(
                self.mode_state_topic,
                self._load_retained_mode_state
            )
            def _publish_if_no_retained():
                self._init_mode_timer = None
                payload = json.dumps(self._value) if not isinstance(self._value, str) else self._value
                client.publish(self.mode_state_topic, payload=payload, qos=0, retain=self.retain)
                _LOGGER.debug("Fallback publish default to %s (%s)", self.mode_state_topic, payload)
            self._init_mode_timer = threading.Timer(10.0, _publish_if_no_retained)
            self._init_mode_timer.start()
            # subscribe to command topic so can receive updates from other end
            client.subscribe(self.mode_command_topic, qos=0)
            client.message_callback_add(
                self.mode_command_topic,
                self._handle_mode_command_message
            )
    
    def _load_retained_mode_state(self, client, userdata, msg):
        # cancel fallback
        if self._init_mode_timer:
            self._init_mode_timer.cancel()
            self._init_mode_timer = None

        val = msg.payload.decode("utf-8")
        with self._mode_lock:
            self._mode = val
        self.handle_mode_command(val)
        _LOGGER.debug("Loaded initial retained state %s = %r", msg.topic, val)

        # NOW unsubscribe and remove our callback so our own publishes
        # don’t come back through here
        client.unsubscribe(self.mode_state_topic)
        client.message_callback_remove(self.mode_state_topic)

    def _handle_mode_command_message(self, client, userdata, msg: mqtt.MQTTMessage) -> None:
        payload = msg.payload.decode("utf-8")
        self.handle_mode_command(payload)

    def build_topics(self, device: MQTTDevice):
        prefix_id = self.build_prefix_id(device)
        base_prefix= f"{self.domain}/{prefix_id}/{self.object_id}"
        
        self.state_topic=f"{base_prefix}/target_temperature/state"
        self.command_topic=f"{base_prefix}/target_temperature/set"
        self.current_temperature_topic = f"{base_prefix}/current_temperature"
        self.current_humidity_topic = f"{base_prefix}/current_humidity"
        self.mode_state_topic = f"{base_prefix}/mode/state"
        self.mode_command_topic = f"{base_prefix}/mode/set"

    @property
    def current_temperature(self) -> Optional[Union[str, float]]:
        with self._temp_lock:
            return self._current_temperature

    @current_temperature.setter
    def current_temperature(self, value: Union[str, float]) -> None:
        with self._temp_lock: 
            self._current_temperature = value
        payload: str = json.dumps(value) if not isinstance(value, str) else value
        if self.client: 
            self.client.publish(self.current_temperature_topic, payload=payload, qos=0, retain=self.retain)
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
                self.client.publish(self.mode_state_topic, payload=value, qos=0, retain=self.retain)
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
            self.client.publish(self.current_humidity_topic, payload=payload, qos=0, retain=self.retain)
            _LOGGER.debug("Published current humidity (%s)", payload)

    def handle_mode_command(self, payload: str) -> None:
        """Called externally when a mode command is received."""
        if payload in self.modes:
            if self._on_mode_command:
                try:
                    self._on_mode_command(payload)
                except Exception:
                    _LOGGER.exception("Error in mode command handler")
        else:
            _LOGGER.warning("Received unsupported mode via command_topic: %s", payload)

    def discovery_payload(self, device) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "name": self.name,
            "unique_id": f"{device.deviceid}_{self.object_id}",
            "state_topic": self.state_topic,
            "device": device.to_dict(),
            "current_temperature_topic": self.current_temperature_topic,
            "mode_state_topic": self.mode_state_topic,
            "mode_command_topic": self.mode_command_topic,
            "temperature_state_topic": self.state_topic,
            "temperature_command_topic": self.command_topic,
            "temp_step": self.step,
            "modes": self.modes,
            "current_humidity_topic": self.current_humidity_topic,
            "min_temp": self.min_temp,
            "max_temp": self.max_temp,
        }
        return payload