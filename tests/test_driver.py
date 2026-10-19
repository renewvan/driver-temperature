import json
from pathlib import Path

from node_temperature.config import load_config
from node_temperature.driver import (
    Sensor,
    adopt_unconfigured_probes,
    apply_persisted_state,
    build_sensors,
    handle_set_command,
    poll_once,
    save_state_field,
)

GOOD = "72 01 : crc=57 YES\n72 01 t=4200\n"
SERIAL_A = "28-00000000000a"
SERIAL_B = "28-00000000000b"


class FakePublisher:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    def publish(self, topic: str, payload: str) -> None:
        self.published.append((topic, payload))

    def latest(self) -> dict[str, object]:
        return {t: json.loads(p) for t, p in self.published}


def make_w1(base: Path, serial: str, text: str = GOOD) -> None:
    (base / serial).mkdir(parents=True)
    (base / serial / "w1_slave").write_text(text)


def make_config(tmp_path: Path, extra: str = ""):
    base = tmp_path / "w1"
    base.mkdir(exist_ok=True)
    zone = tmp_path / "zone"
    zone.write_text("51600\n")
    local = tmp_path / "config.ini"
    local.write_text(
        f"[node]\nw1_base_path = {base}\ncpu_thermal_zone = {zone}\n"
        f"state_dir = {tmp_path / 'state'}\n{extra}"
    )
    return load_config(local_path=local), base


def test_poll_publishes_identity_and_live_for_configured_probe(tmp_path: Path) -> None:
    config, base = make_config(
        tmp_path, f"[sensor.fridge]\nserial = {SERIAL_A}\nname = Fridge\nunit = F\n"
    )
    make_w1(base, SERIAL_A)
    pub = FakePublisher()
    sensors = build_sensors(config)
    poll_once(pub, config, sensors)

    out = pub.latest()
    p = "renewvan/temperature/fridge/"
    assert out[p + "name"] == "Fridge"
    assert out[p + "unit"] == "F"
    assert out[p + "source"] == "w1"
    assert out[p + "serial"] == SERIAL_A
    assert out[p + "temperature_c"] == 4.2  # wire stays Celsius even though unit = F
    assert out[p + "status"] == "ok"
    assert out["renewvan/temperature/cpu/temperature_c"] == 51.6
    assert "renewvan/temperature/cpu/serial" not in out


def test_identity_published_once_live_every_poll(tmp_path: Path) -> None:
    config, base = make_config(tmp_path)
    make_w1(base, SERIAL_A)
    pub = FakePublisher()
    sensors = build_sensors(config)
    poll_once(pub, config, sensors)
    poll_once(pub, config, sensors)
    topics = [t for t, _ in pub.published]
    assert topics.count(f"renewvan/temperature/{SERIAL_A}/name") == 1
    assert topics.count(f"renewvan/temperature/{SERIAL_A}/temperature_c") == 2


def test_unconfigured_probe_adopted_with_serial_as_id(tmp_path: Path) -> None:
    config, base = make_config(tmp_path, f"[sensor.fridge]\nserial = {SERIAL_A}\n")
    make_w1(base, SERIAL_A)
    make_w1(base, SERIAL_B)
    sensors = build_sensors(config)
    added = adopt_unconfigured_probes(config, sensors)
    assert [s.id for s in added] == [SERIAL_B]  # configured probe not duplicated
    assert sensors[SERIAL_B].name == SERIAL_B


def test_missing_w1_overlay_still_serves_cpu(tmp_path: Path) -> None:
    config, base = make_config(tmp_path)
    base.rmdir()
    pub = FakePublisher()
    poll_once(pub, config, build_sensors(config))
    assert pub.latest()["renewvan/temperature/cpu/status"] == "ok"


def test_bad_read_publishes_status_and_skips_temperature(tmp_path: Path) -> None:
    config, base = make_config(tmp_path, f"[sensor.fridge]\nserial = {SERIAL_A}\n")
    make_w1(base, SERIAL_A, "72 01 : crc=57 NO\n72 01 t=4200\n")
    pub = FakePublisher()
    poll_once(pub, config, build_sensors(config))
    out = pub.latest()
    assert out["renewvan/temperature/fridge/status"] == "no_reading"
    assert "renewvan/temperature/fridge/temperature_c" not in out


def test_unplugged_probe_reports_disconnected_then_recovers(tmp_path: Path) -> None:
    config, base = make_config(tmp_path, f"[sensor.fridge]\nserial = {SERIAL_A}\n")
    pub = FakePublisher()
    sensors = build_sensors(config)
    poll_once(pub, config, sensors)
    assert pub.latest()["renewvan/temperature/fridge/status"] == "disconnected"
    make_w1(base, SERIAL_A)
    poll_once(pub, config, sensors)
    assert pub.latest()["renewvan/temperature/fridge/status"] == "ok"


def test_set_unit_persists_republishes_and_survives_restart(tmp_path: Path) -> None:
    config, _ = make_config(tmp_path, f"[sensor.fridge]\nserial = {SERIAL_A}\nunit = C\n")
    state = tmp_path / "state"
    pub = FakePublisher()
    sensors = build_sensors(config)
    handle_set_command(pub, sensors["fridge"], "unit", json.dumps("f"), state)
    assert pub.latest()["renewvan/temperature/fridge/unit"] == "F"
    # "restart": rebuild from config.ini; persisted edit beats the config default
    assert build_sensors(config)["fridge"].unit == "F"


def test_set_name_persists_and_overrides_config(tmp_path: Path) -> None:
    config, _ = make_config(tmp_path, f"[sensor.fridge]\nserial = {SERIAL_A}\nname = Old\n")
    state = tmp_path / "state"
    sensors = build_sensors(config)
    handle_set_command(FakePublisher(), sensors["fridge"], "name", json.dumps(" Galley "), state)
    assert build_sensors(config)["fridge"].name == "Galley"


def test_invalid_set_is_rejected_without_side_effects(tmp_path: Path) -> None:
    state = tmp_path / "state"
    sensor = Sensor(id="x", source="cpu", name="X", unit="C")
    pub = FakePublisher()
    for field_name, payload in [
        ("unit", json.dumps("K")),
        ("unit", json.dumps(5)),
        ("unit", "not json"),
        ("name", json.dumps("   ")),
        ("name", json.dumps(["a"])),
    ]:
        handle_set_command(pub, sensor, field_name, payload, state)
    assert pub.published == []
    assert (sensor.name, sensor.unit) == ("X", "C")
    assert not state.exists()


def test_failed_persist_rejects_the_edit(tmp_path: Path) -> None:
    blocker = tmp_path / "state"
    blocker.write_text("a file, so mkdir fails")
    sensor = Sensor(id="x", source="cpu", name="X", unit="C")
    pub = FakePublisher()
    handle_set_command(pub, sensor, "unit", json.dumps("F"), blocker)
    assert pub.published == []
    assert sensor.unit == "C"


def test_corrupt_or_invalid_state_is_ignored(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    (state / "x.json").write_text("{not json")
    sensor = Sensor(id="x", source="cpu", name="X", unit="C")
    apply_persisted_state(sensor, state)
    assert (sensor.name, sensor.unit) == ("X", "C")
    save_state_field("x", "unit", "K", state)  # invalid value on disk
    apply_persisted_state(sensor, state)
    assert sensor.unit == "C"


def test_run_stamps_node_version_env_into_published_info(tmp_path: Path, monkeypatch) -> None:
    import json as _json

    import node_temperature.driver as driver

    config, _ = make_config(tmp_path)
    captured: dict[str, str] = {}

    class StopRun(Exception):
        pass

    class SpyPublisher:
        def __init__(self, mqtt_config, info: str) -> None:
            captured["info"] = info

        def connect(self) -> None:
            raise StopRun

        def disconnect(self) -> None: ...

    monkeypatch.setattr(driver, "Publisher", SpyPublisher)
    monkeypatch.setattr(driver, "read_host_serial", lambda: None)

    for env, expected in (("v4.5.6", "v4.5.6"), (None, "dev")):
        if env is None:
            monkeypatch.delenv("NODE_VERSION", raising=False)
        else:
            monkeypatch.setenv("NODE_VERSION", env)
        try:
            driver.run(config)
        except StopRun:
            pass
        assert _json.loads(captured["info"])["version"] == expected
