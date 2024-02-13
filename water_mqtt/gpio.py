"""
Water meter impulse counter to MQTT gateway

This file contains the GPIO specific parts
"""

import logging
import multiprocessing
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List

import gpiod
from gpiod.line import Bias, Edge

LOGGER = logging.getLogger(__name__)


EVENT_NAMES = {
    gpiod.EdgeEvent.Type.RISING_EDGE: "RISING_EDGE",
    gpiod.EdgeEvent.Type.FALLING_EDGE: "FALLING_EDGE",
}


def event_time(event):
    """
    Return the time of the event as a float
    """

    return event.timestamp_ns / 1_000_000_000


def log_events(events):
    """
    Print the contents of the passed event log,
    in reverse order
    """
    LOGGER.debug("Last events:")
    for i in range(0, len(events) - 1):
        this_time = event_time(events[i])
        prev_time = event_time(events[i + 1])
        LOGGER.debug(
            "  Event %s at %f, delta %fs",
            EVENT_NAMES.get(events[i].type, "UNKNOWN"),
            this_time,
            this_time - prev_time,
        )

    LOGGER.debug(
        "  Event %s at %f",
        EVENT_NAMES.get(events[-1].type, "UNKNOWN"),
        event_time(events[-1]),
    )


def gpio_main(
    counter,
    mqtt_queue: multiprocessing.Queue,
    config: Dict[str, Any],
) -> None:
    """
    Main function for the GPIO reading process

    Prepare the event handler for the GPIO pin, wait for events,
    debounce as needed, increase the counter, and push to the queue

    `counter_value` is a shared value between this process and
    the web server process, to allow changing the value without having
    to restart the entire program.
    """

    LOGGER.info("gpio process starting")

    # Count debounced events, for debugging
    debounced = 0

    # Last events received
    last_events: List[gpiod.EdgeEvent] = []
    keep_last = 10
    last_ev_timestamps = {
        gpiod.EdgeEvent.Type.RISING_EDGE: 0,
        gpiod.EdgeEvent.Type.FALLING_EDGE: 0,
    }

    with gpiod.request_lines(
        config["gpiochip"],
        consumer=Path(sys.argv[0]).name,
        config={
            config["line"]: gpiod.LineSettings(
                bias=Bias.PULL_UP,
                edge_detection=Edge.BOTH,
                debounce_period=timedelta(milliseconds=200),
            ),
        },
    ) as request:

        while True:
            # Wait for 60 seconds. If nothing happens in that time,
            # send an event anyway with the current counter
            res = request.wait_edge_events(timeout=timedelta(seconds=60))
            if res:
                for event in request.read_edge_events():
                    LOGGER.debug(
                        "Line: %d, Event: %s, Event# %d",
                        event.line_offset,
                        EVENT_NAMES.get(event.event_type, "UNKNOWN"),
                        event.line_seqno,
                    )

                    last_events.insert(0, event)
                    last_events = last_events[:keep_last]

                    delta_time = (
                        event_time(event) - last_ev_timestamps[event.event_type]
                    )
                    last_ev_timestamps[event.event_type] = event_time(event)
                    LOGGER.debug(
                        "Updating last seen timestamp for %s to %f",
                        EVENT_NAMES.get(event.event_type, "UNKNOWN"),
                        event_time(event),
                    )

                    if delta_time < 0.2:
                        LOGGER.debug(
                            "Suspiciously small event delta: %.6fs, ignoring",
                            delta_time,
                        )
                        log_events(last_events)
                        debounced += 1
                        continue

                    if event.event_type == gpiod.EdgeEvent.Type.FALLING_EDGE:
                        with counter.get_lock():
                            counter.value += 1
                            LOGGER.info(
                                "Counter: %d, delta %.6fs (debounced: %d)",
                                counter.value,
                                delta_time,
                                debounced,
                            )

            with counter.get_lock():
                data = {
                    "water_mqtt_timestamp": int(time.time() * 1000),
                    "counter": counter.value,
                    "debounced": debounced,
                    "serial": config["serial"],
                }

            try:
                mqtt_queue.put(data, block=False)
            except Exception:
                # Ignore this
                pass
