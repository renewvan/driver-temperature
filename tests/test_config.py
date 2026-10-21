from pathlib import Path

import pytest

from driver_temperature.config import load_config


def test_load_config_defaults() -> None:
    config = load_config()
    assert config.mqtt.port == 1883
    assert config.device.sensors == ()
    assert config.device.cpu is not None
    assert (config.device.cpu.id, config.device.cpu.unit) == ("cpu", "C")


def test_load_config_local_override(tmp_path: Path) -> None:
    local = tmp_path / "config.ini"
    local.write_text("[mqtt]\nhost = 192.168.1.50\n")
    config = load_config(local_path=local)
    assert config.mqtt.host == "192.168.1.50"


def _load(tmp_path: Path, body: str):
    local = tmp_path / "config.ini"
    local.write_text(body)
    return load_config(local_path=local)


def test_sensor_sections_inherit_defaults(tmp_path: Path) -> None:
    config = _load(
        tmp_path,
        "[device]\ndefault_unit = F\n[sensor.fridge]\nserial = 28-0000075A1B2C\n",
    )
    (sensor,) = config.device.sensors
    assert (sensor.id, sensor.name, sensor.unit) == ("fridge", "fridge", "F")
    assert sensor.serial == "28-0000075a1b2c"  # lowercased


def test_sensor_section_overrides(tmp_path: Path) -> None:
    config = _load(
        tmp_path,
        "[sensor.cabin]\nserial = 28-000000000001\nname = Cabin air\nunit = f\n",
    )
    (sensor,) = config.device.sensors
    assert (sensor.name, sensor.unit) == ("Cabin air", "F")


@pytest.mark.parametrize(
    "body",
    [
        "[sensor.a]\nname = x\n",  # missing serial
        "[sensor.a]\nserial = 28-zzzz\n",  # malformed serial
        "[sensor.a]\nserial = 28-000000000001\nunit = K\n",  # bad unit
        "[sensor.a/b]\nserial = 28-000000000001\n",  # topic-unsafe id
        "[sensor.a]\nserial = 28-000000000001\n[sensor.b]\nserial = 28-000000000001\n",  # dup
        "[sensor.cpu]\nserial = 28-000000000001\n",  # collides with built-in
        "[device]\ndefault_unit = K\n",
    ],
)
def test_invalid_config_fails_loudly(tmp_path: Path, body: str) -> None:
    with pytest.raises(ValueError):
        _load(tmp_path, body)


def test_cpu_can_be_disabled(tmp_path: Path) -> None:
    assert _load(tmp_path, "[device]\ncpu_enabled = false\n").device.cpu is None
