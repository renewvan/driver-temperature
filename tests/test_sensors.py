import pytest

from node_temperature.sensors import (
    STATUS_NO_READING,
    STATUS_OK,
    SensorReadError,
    normalize_name,
    normalize_unit,
    parse_thermal_zone,
    parse_w1_slave,
    to_reading,
)

GOOD = "72 01 4b 46 7f ff 0e 10 57 : crc=57 YES\n72 01 4b 46 7f ff 0e 10 57 t=23125\n"


def test_w1_parses_millidegrees():
    assert parse_w1_slave(GOOD) == pytest.approx(23.125)


def test_w1_parses_negative():
    text = "00 00 00 00 00 00 00 00 00 : crc=00 YES\n00 00 00 00 00 00 00 00 00 t=-12500\n"
    assert parse_w1_slave(text) == pytest.approx(-12.5)


@pytest.mark.parametrize(
    "text",
    [
        "72 01 : crc=57 NO\n72 01 t=23125\n",  # CRC failure
        "72 01 : crc=57 YES\n",  # truncated
        "72 01 : crc=57 YES\n72 01 no-temp\n",  # no t=
        "72 01 : crc=57 YES\n72 01 t=abc\n",  # non-numeric
        "72 01 : crc=57 YES\n72 01 t=85000\n",  # power-on default
        "72 01 : crc=57 YES\n72 01 t=-60000\n",  # below range
        "",
    ],
)
def test_w1_rejects_bad_data(text):
    with pytest.raises(SensorReadError):
        parse_w1_slave(text)


def test_thermal_zone_millidegrees():
    assert parse_thermal_zone("51612\n") == pytest.approx(51.612)


@pytest.mark.parametrize("text", ["", "hot", "999999"])
def test_thermal_zone_rejects_bad_data(text):
    with pytest.raises(SensorReadError):
        parse_thermal_zone(text)


def test_reading_rounds_and_flags():
    ok = to_reading(23.12567, None)
    assert (ok.status, ok.temperature_c) == (STATUS_OK, 23.13)
    bad = to_reading(None, SensorReadError("x"))
    assert (bad.status, bad.temperature_c) == (STATUS_NO_READING, None)


def test_normalize_unit_and_name():
    assert normalize_unit(" f ") == "F"
    assert normalize_unit("K") is None
    assert normalize_name("  Fridge ") == "Fridge"
    assert normalize_name("   ") is None
