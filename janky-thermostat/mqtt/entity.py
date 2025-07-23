import threading
from typing import Optional, Callable, Union, Dict, Any
import json
import logging

import paho.mqtt.client as mqtt

from .device import MQTTDevice

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
                 on_command: Optional[Callable[[Any], None]] = None
                ) -> None:
        self.domain: str = domain
        self.object_id: str = object_id
        self.name: str = name
        self.unit: Optional[str] = unit
        self.device_class: Optional[str] = device_class
        self.retain: bool = retain

        self._value_lock: threading.Lock = threading.Lock()
        self._value: Optional[Union[str, float]] = value
        self.client: Optional[mqtt.Client] = None
        self.state_topic: str = state_topic
        self.command_topic: str = command_topic
        # Optional command handler
        self._on_command: Optional[Callable[[Union[str, float, dict]], None]] = on_command
        if self._on_command and self.domain == "sensor":
            raise ValueError("Sensors cannot have a command handler")
        if self.domain == "number" and self._on_command is None:
            raise ValueError("Numbers require a command handler")
        self._init_timer: threading.Timer | None = None

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
            self.client.publish(self.state_topic, payload=payload, qos=0, retain=self.retain)
            _LOGGER.debug("Publish to %s (%s)", self.state_topic, payload)
        else:
            _LOGGER.debug("MQTT client not set for entity '%s'; publish skipped", self.object_id)
    
    def _on_connect(self, client: mqtt.Client):
        self.client = client
        if self._on_command:
            # subscribe to own state topic so can get old value
            client.subscribe(self.state_topic, qos=0)
            client.message_callback_add(
                self.state_topic,
                self._load_retained_state
            )
            def _publish_if_no_retained():
                self._init_timer = None
                payload = json.dumps(self._value) if not isinstance(self._value, str) else self._value
                client.publish(self.state_topic, payload=payload, qos=0, retain=self.retain)
                _LOGGER.debug("Fallback publish default to %s (%s)", self.state_topic, payload)
            self._init_timer = threading.Timer(10.0, _publish_if_no_retained)
            self._init_timer.start()
            # subscribe to command topic so can receive updates from other end
            client.subscribe(self.command_topic, qos=0)
            client.message_callback_add(
                self.command_topic,
                self._handle_command_message
            )

    def _load_retained_state(self, client, userdata, msg):
        # cancel fallback
        if self._init_timer:
            self._init_timer.cancel()
            self._init_timer = None

        val = self._parsePayload(msg.payload)
        with self._value_lock:
            self._value = val
        self.on_command(val)
        _LOGGER.debug("Loaded initial retained state %s = %r", msg.topic, val)

        # NOW unsubscribe and remove our callback so our own publishes
        # don’t come back through here
        client.unsubscribe(self.state_topic)
        client.message_callback_remove(self.state_topic)

    def _handle_command_message(self, client, userdata, msg: mqtt.MQTTMessage) -> None:
        payload = self._parsePayload(msg.payload)
        self.on_command(payload)

    @staticmethod
    def _parsePayload(payload: bytes) -> Union[str, float]:
        text = payload.decode("utf-8")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def forcePublish(self):
        if self.client:
            payload: str = json.dumps(self._value)
            self.client.publish(self.state_topic, payload=payload, qos=0, retain=self.retain)
            _LOGGER.debug("Publish to %s (%s)", self.state_topic, payload)
        else:
            _LOGGER.debug("MQTT client not set for entity '%s'; publish skipped", self.object_id)

    def getFloat(self) -> float:
        return 0 if self.value is None else float(self.value)
    
    def build_prefix_id(self, device: MQTTDevice):
        device_id = device.identifiers[0]
        prefix_id  = device_id if device_id else self.object_id
        return prefix_id
    def build_topics(self, device: MQTTDevice):
        prefix_id = self.build_prefix_id(device)
        base_prefix= f"{self.domain}/{prefix_id}/{self.object_id}"
        if self.state_topic == "":
            self.state_topic = f"{base_prefix}/state"
        if self.command_topic == "":
            self.command_topic = f"{base_prefix}/set"

    def discovery_topic(self, device: MQTTDevice) -> str:
        return f"homeassistant/{self.domain}/{device.deviceid}_{self.object_id}/config"

    def discovery_payload(self, device: MQTTDevice) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "name": self.name,
            "unique_id": f"{device.deviceid}_{self.object_id}",
            "state_topic": self.state_topic,
            "device": device.to_dict()
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
