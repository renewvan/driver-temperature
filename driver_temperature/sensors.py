"""Pure temperature-sensor parsing and classification -- no I/O.

Same split as driver-tank's calibration.py: everything here takes raw text/
numbers in and returns a value out, so it is fixture-testable without a
Pi. The filesystem reads live in reader.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 1-Wire family code 0x28 = DS18B20; sysfs names the device 28-<12 hex>.
W1_SERIAL_RE = re.compile(r"^28-[0-9a-f]{12}$")

# The DS18B20 scratchpad powers up holding +85.0 C. Seeing exactly that means
# the conversion never ran (weak pull-up / parasitic power starved), not that
# the probe is genuinely at 85 C.
_W1_POWER_ON_MILLI_C = 85000

# Valid range published in hub/schema/temperature.schema.json.
MIN_C = -55.0
MAX_C = 150.0

STATUS_OK = "ok"
STATUS_NO_READING = "no_reading"
STATUS_DISCONNECTED = "disconnected"


class SensorReadError(ValueError):
    """Raw sensor data was present but unusable (CRC fail, power-on default, garbage)."""


@dataclass(frozen=True)
class Reading:
    status: str
    temperature_c: float | None  # None unless status == STATUS_OK


def parse_w1_slave(text: str) -> float:
    """Parse a DS18B20 /sys/bus/w1/devices/<serial>/w1_slave dump into Celsius.

    Format (two lines):
        72 01 4b 46 7f ff 0e 10 57 : crc=57 YES
        72 01 4b 46 7f ff 0e 10 57 t=23125

    Raises:
        SensorReadError: CRC not YES, no t= field, the 85.0 C power-on
            default, or a value outside the schema range.
    """
    lines = text.strip().splitlines()
    if len(lines) < 2 or not lines[0].rstrip().endswith("YES"):
        raise SensorReadError("1-Wire CRC check failed")

    _, sep, raw = lines[1].partition("t=")
    if not sep:
        raise SensorReadError("1-Wire output has no t= field")
    try:
        milli_c = int(raw.strip())
    except ValueError as e:
        raise SensorReadError(f"1-Wire t= field is not an integer: {raw!r}") from e

    if milli_c == _W1_POWER_ON_MILLI_C:
        raise SensorReadError("1-Wire probe returned the 85.0 C power-on default")
    return _check_range(milli_c / 1000.0)


def parse_thermal_zone(text: str) -> float:
    """Parse /sys/class/thermal/thermal_zone*/temp (millidegrees C) into Celsius."""
    try:
        milli_c = int(text.strip())
    except ValueError as e:
        raise SensorReadError(f"thermal zone value is not an integer: {text!r}") from e
    return _check_range(milli_c / 1000.0)


def _check_range(celsius: float) -> float:
    if not MIN_C <= celsius <= MAX_C:
        raise SensorReadError(f"{celsius} C is outside {MIN_C}..{MAX_C} C")
    return celsius


def to_reading(celsius: float | None, error: SensorReadError | None) -> Reading:
    """Collapse a parse result into the wire status + optional value."""
    if error is not None or celsius is None:
        return Reading(STATUS_NO_READING, None)
    return Reading(STATUS_OK, round(celsius, 2))


def normalize_unit(value: str) -> str | None:
    """Accept 'c'/'C'/'f'/'F' (any case, surrounding whitespace); None if invalid."""
    unit = value.strip().upper()
    return unit if unit in ("C", "F") else None


def normalize_name(value: str) -> str | None:
    """Trim a user-supplied label; None if empty after trimming."""
    name = value.strip()
    return name or None
