"""
Water meter impulse counter to MQTT gateway

This file contains the GPIO specific parts
"""

import logging
import multiprocessing
import sys
import time
from typing import Any, Dict, List

import gpiod

LOGGER = logging.getLogger(__name__)


EVENT_NAMES = {
    gpiod.LineEvent.RISING_EDGE: "RISING_EDGE",
    gpiod.LineEvent.FALLING_EDGE: "FALLING_EDGE",
}


def event_time(event):
    """
    Return the time of the event as a float
    """

    return event.sec + (event.nsec / 1_000_000_000)


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
    last_events: List[gpiod.LineEvent] = []
    keep_last = 10
    last_ev_timestamps = {
        gpiod.LineEvent.RISING_EDGE: 0,
        gpiod.LineEvent.FALLING_EDGE: 0,
    }

    with gpiod.Chip(config["gpiochip"]) as chip:
        offsets = [
            config["line"],
        ]

        lines = chip.get_lines(offsets)
        lines.request(
            consumer=sys.argv[0],
            type=gpiod.LINE_REQ_EV_BOTH_EDGES,
            flags=gpiod.LINE_REQ_FLAG_BIAS_PULL_UP,
        )

        while True:
            # The gpiod python binding don't implement 'wait forever'
            ev_lines = lines.event_wait(sec=3600)
            if ev_lines:
                for line in ev_lines:
                    event = line.event_read()
                    LOGGER.debug("Event: %s", EVENT_NAMES.get(event.type, "UNKNOWN"))

                    last_events.insert(0, event)
                    last_events = last_events[:keep_last]

                    delta_time = event_time(event) - last_ev_timestamps[event.type]
                    last_ev_timestamps[event.type] = event_time(event)
                    LOGGER.debug(
                        "Updating last seen timestamp for %s to %f",
                        EVENT_NAMES.get(event.type, "UNKNOWN"),
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

                    if event.type == gpiod.LineEvent.FALLING_EDGE:
                        with counter.get_lock():
                            counter.value += 1
                            LOGGER.info(
                                "Counter: %d, delta %s (debounced: %d)",
                                counter.value,
                                delta_time,
                                debounced,
                            )

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
