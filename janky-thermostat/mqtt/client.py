from .device import MQTTDevice

DEVICE = MQTTDevice("janky-thermostat", "Janky Thermostat", "n/a", "1")

from typing import List, Optional, Union, Any
import paho.mqtt.client as mqtt
import json
import logging

from .entity import MQTTEntity

_LOGGER = logging.getLogger(__name__)

class MQTTClient:
    def __init__(self,
                 broker: str,
                 port: int = 1883,
                 device: MQTTDevice = DEVICE,
                 username: Optional[str] = None,
                 password: Optional[str] = None) -> None:
        self.broker: str = broker
        self.port: int = port
        self.client: mqtt.Client = mqtt.Client(client_id=device.deviceid)
        if username and password:
            self.client.username_pw_set(username, password)
        self.device: MQTTDevice = device
        self.entities: List[MQTTEntity] = []

        # Paho callbacks
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def register_entity(self, entity: MQTTEntity) -> MQTTEntity:
        """Add an entity and subscribe to its command topic if defined."""
        entity.build_topics(self.device)
        self.entities.append(entity)
        return entity

    def connect(self) -> None:
        """Establish connection and start background loop."""
        self.client.connect(self.broker, self.port)
        self.client.loop_start()

    def _on_connect(self,
                    client: mqtt.Client,
                    userdata: Any,
                    flags: dict,
                    rc: int) -> None:
        _LOGGER.info("Connected to MQTT (%s:%s)", self.broker, self.port)

        # Ensure subscriptions are active
        for entity in self.entities:
            if entity.command_topic:
                client.subscribe(entity.command_topic)
                _LOGGER.debug("Subscribed to %s", entity.command_topic)

        # Publish discovery configs
        self.publish_discovery_configs()

    def _on_message(self,
                    client: mqtt.Client,
                    userdata: Any,
                    msg: mqtt.MQTTMessage) -> None:
        topic: str = msg.topic
        payload: str = msg.payload.decode("utf-8", errors="ignore")

        for entity in self.entities:
            if entity.command_topic == topic and hasattr(entity, "on_command"):
                try:
                    entity.on_command(self._parse(payload))
                except Exception:
                    _LOGGER.exception("Error in on_command for %s", topic)

    def publish_discovery_configs(self) -> None:
        for entity in self.entities:
            topic: str = entity.discovery_topic()
            payload: dict = entity.discovery_payload(self.device)
            self.client.publish(topic, json.dumps(payload), retain=True)
            _LOGGER.debug("Published discovery %s -> %s", entity.object_id, topic)

    def _parse(self, payload: str) -> Union[str, float, dict]:
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return payload
