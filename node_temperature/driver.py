"""Publish loop: TODO describe Temperature read -> publish ->
renewvan/temperature/<id>/<property>.

This is a scaffolded stub -- see the design checklist in README.md. Fill
in, in order:

1. A reader for the physical hardware/feed (see node-tank's adc.py for a
   node that owns the sensing, or node-battery's Victron MQTT subscription
   for a node that remaps an existing feed -- Q1 of the design round
   decides which shape this is).
2. The fields this node publishes, matching a hub/schema/<entity>.schema.json
   contract (new entity) or an existing one (Q2/Q3 of the design round).
3. Identity fields (published once at startup) vs live fields (republished
   every poll) -- see node-tank's publish_identity()/read_and_publish()
   split for the pattern.
"""

from __future__ import annotations

import logging
import time

from node_temperature.config import AppConfig
from node_temperature.publisher import Publisher

logger = logging.getLogger(__name__)


def _topic(node_id: str, prop: str) -> str:
    return f"renewvan/temperature/{node_id}/{prop}"


def read_and_publish(publisher: Publisher, config: AppConfig) -> None:
    """TODO: read the hardware/feed and publish live fields via
    publisher.publish(_topic(config.node.id, "<property>"), payload).
    """
    raise NotImplementedError(
        "Implement the Temperature read+publish step (see this module's docstring)"
    )


def run(config: AppConfig) -> None:
    publisher = Publisher(config.mqtt)
    publisher.connect()
    try:
        while True:
            read_and_publish(publisher, config)
            time.sleep(config.node.update_interval_ms / 1000)
    except KeyboardInterrupt:
        logger.info("Shutting down")
    finally:
        publisher.disconnect()
