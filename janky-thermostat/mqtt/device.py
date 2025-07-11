from dataclasses import dataclass, asdict, field

@dataclass
class MQTTDevice:
    deviceid:      str
    name:          str
    manufacturer:  str = "n/a"
    version:       str = "1"
    identifiers:   list[str] = field(init=False)
    model:         str       = field(init=False)

    def __post_init__(self):
        self.identifiers = [self.deviceid]
        self.model       = f"{self.deviceid} v{self.version}"

    def to_dict(self) -> dict:
        data = asdict(self)
        # Rename 'version' → 'sw_version' for HA spec
        data["sw_version"] = data.pop("version")
        return data
