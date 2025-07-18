from dataclasses import dataclass, asdict, field

@dataclass
class MQTTDevice:
    deviceid:      str
    name:          str
    model:         str
    manufacturer:  str = "n/a"
    sw_version:    str = "1"
    identifiers:   list[str] = field(init=False)

    def __post_init__(self):
        self.identifiers = [self.deviceid]

    def to_dict(self) -> dict:
        data = asdict(self)
        data.pop("deviceid")
        return data
