from typing import Any, Callable, Dict, Optional

from .entity import MQTTEntity
from .device import MQTTDevice

class NumberEntity(MQTTEntity):
    def __init__(
        self,
        object_id: str,
        name: str,
        *,
        min_value: float,
        max_value: float,
        value: float = 0.0,
        step: float = 1.0,
        unit: Optional[str] = None,
        retain: bool = True,
        on_command: Callable[[float], None]
    ):
        super().__init__(
            domain="number",
            object_id=object_id,
            name=name,
            value=value,
            unit=unit,
            retain=retain,
            on_command=on_command
        )
        self.min = min_value
        self.max = max_value
        self.step = step

    def discovery_payload(self, device: MQTTDevice) -> Dict[str, Any]:
        payload = super().discovery_payload(device)
        payload.update({
            "min": self.min,
            "max": self.max,
            "step": self.step,
        })
        return payload
