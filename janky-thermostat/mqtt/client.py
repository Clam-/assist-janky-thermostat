from .device import MQTTDevice

DEVICE = MQTTDevice("janky-thermostat", "Janky Thermostat", "Janky Thermo v1")

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

    def register_entity(self, entity: MQTTEntity) -> MQTTEntity:
        """Add an entity and subscribe to its command topic if defined."""
        entity.build_topics(self.device)
        self.entities.append(entity)
        return entity

    def connect(self) -> None:
        """Establish connection and start background loop."""
        self.client.loop_start()
        self.client.connect(self.broker, self.port)

    def _on_connect(self,
                    client: mqtt.Client,
                    userdata: Any,
                    flags: dict,
                    rc: int) -> None:
        _LOGGER.info("Connected to MQTT (%s:%s)", self.broker, self.port)
        # register client in entities and setup callbacks
        for entity in self.entities:
            entity._on_connect(self.client)
        # Publish discovery configs
        self.publish_discovery_configs()

    def publish_discovery_configs(self) -> None:
        for entity in self.entities:
            topic: str = entity.discovery_topic(self.device)
            payload: dict = entity.discovery_payload(self.device)
            self.client.publish(topic, payload=json.dumps(payload), qos=0, retain=True)
            _LOGGER.debug("Published discovery %s -> %s", entity.object_id, topic)

