"""
This file contains the CLI script entry points
"""

import argparse
import codecs
import configparser
import logging
import multiprocessing
import os
import time
from typing import Any, Dict, List

from .gpio import gpio_main
from .http import http_main
from .mqtt import mqtt_main

logging.basicConfig(
    format="%(asctime)-15s %(levelname)s: %(message)s", level=logging.INFO
)
LOGGER = logging.getLogger(__name__)

# Default values for command line args
DEFAULTS: Dict[str, Any] = {
    "mqtt_port": 1883,
    "buffer_size": 100000,
    "mqtt_topic": "water-mqtt/tele/%(serial)s/SENSOR",
    "mqtt_client_id": "water-mqtt-gateway",
    "http_host": "localhost",
    "http_port": 5000,
    "counter_file": "/var/lib/water_mqtt/counter",
}


def load_config_file(filename: str) -> Dict[str, Any]:
    """
    Load the ini style config file given by `filename`
    """

    config: Dict[str, Any] = {}
    ini = configparser.ConfigParser()
    try:
        with codecs.open(filename, encoding="utf-8") as configfile:
            ini.read_file(configfile)
    except Exception as exc:
        LOGGER.error("Could not read config file %s: %s", filename, exc)
        raise SystemExit(1)

    if ini.has_option("general", "mqtt-host"):
        config["mqtt_host"] = ini.get("general", "mqtt-host")

    try:
        if ini.has_option("general", "mqtt-port"):
            config["mqtt_port"] = ini.getint("general", "mqtt-port")
    except ValueError:
        LOGGER.error(
            "%s: %s is not a valid value for mqtt-port",
            filename,
            ini.get("general", "mqtt-port"),
        )
        raise SystemExit(1)

    if ini.has_option("general", "mqtt-client-id"):
        config["mqtt_client_id"] = ini.get("general", "mqtt-client-id")

    if ini.has_option("general", "serial"):
        config["serial"] = ini.get("general", "serial")

    try:
        if ini.has_option("general", "buffer-size"):
            config["buffer_size"] = ini.getint("general", "buffer-size")
    except ValueError:
        LOGGER.error(
            "%s: %s is not a valid value for buffer-size",
            filename,
            ini.get("general", "buffer-size"),
        )
        raise SystemExit(1)

    if ini.has_option("general", "http-host"):
        config["http_host"] = ini.get("general", "http-host")

    if ini.has_option("general", "counter-file"):
        config["counter_file"] = ini.get("general", "counter-file")

    try:
        if ini.has_option("general", "http-port"):
            config["http_port"] = ini.getint("general", "http-port")
    except ValueError:
        LOGGER.error(
            "%s: %s is not a valid value for http-port",
            filename,
            ini.get("general", "http-port"),
        )
        raise SystemExit(1)

    return config


def load_counter(config, counter) -> None:
    """
    Try to load a counter value from disk.
    Failure to do so is not fatal
    """
    try:
        with open(config["counter_file"], "r", encoding="utf-8") as counterfile:
            new_counter = int(counterfile.readline())
            LOGGER.info("Read counter %d from %s", new_counter, config["counter_file"])
            with counter.get_lock():
                counter.value = new_counter
    except Exception as exc:
        LOGGER.error("Could not read counter from %s: %s", config["counter_file"], exc)


def write_counter(config, counter) -> None:
    """
    Write the counter value to disk.
    Failure to do so is not fatal
    """
    try:
        LOGGER.debug(
            "Writing counter %d to %s",
            counter,
            config["counter_file"],
        )
        with open(config["counter_file"], "w", encoding="utf-8") as counterfile:
            counterfile.write(f"{counter}")
            counterfile.flush()
            os.fsync(counterfile.fileno())
    except Exception as exc:
        LOGGER.error(
            "Error while writing counter to %s: %s",
            config["counter_file"],
            exc,
        )


def water_mqtt() -> None:
    """
    Main function for the water-mqtt script
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, help="Configuration file to load")
    parser.add_argument(
        "--mqtt-topic",
        type=str,
        default=None,
        help="MQTT topic to publish to. May contain python format string "
        "references to variable `serial` (containing the serial number "
        "of the device generating the data)."
        + ("(Default: %(mqtt_topic)s)" % DEFAULTS).replace("%", "%%"),
    )
    parser.add_argument("--mqtt-host", type=str, help="MQTT server to connect to")
    parser.add_argument(
        "--mqtt-port", type=int, default=None, help="MQTT port to connect to"
    )
    parser.add_argument(
        "--mqtt-client-id",
        type=str,
        default=None,
        help="MQTT client ID. Needs to be unique between all clients connecting "
        "to the same broker",
    )
    parser.add_argument(
        "--buffer-size",
        type=int,
        default=None,
        help="How many measurements to buffer if the MQTT "
        "server should be unavailable. This buffer is not "
        "persistent across program restarts.",
    )
    parser.add_argument("--gpiochip", type=str, help="Device file of the GPIO to use")
    parser.add_argument("--line", type=int, help="GPIO line to use")
    parser.add_argument("--serial", type=str, help="Serial number of the meter")
    parser.add_argument(
        "--http-host", type=str, help="Hostname/IP to listen on for HTTP server"
    )
    parser.add_argument(
        "--http-port", type=int, default=None, help="http port to listen on"
    )
    parser.add_argument(
        "--counter-file", type=str, help="File to use to store counter value"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.config:
        config = load_config_file(args.config)
    else:
        config = {}

    LOGGER.debug("Config after loading config file: %s", config)

    if args.mqtt_topic:
        config["mqtt_topic"] = args.mqtt_topic
    elif "mqtt_topic" not in config:
        # Not set through config file, not set through CLI, use default
        config["mqtt_topic"] = DEFAULTS["mqtt_topic"]

    if args.mqtt_host:
        config["mqtt_host"] = args.mqtt_host

    if args.mqtt_port:
        config["mqtt_port"] = args.mqtt_port
    elif "mqtt_port" not in config:
        # Not set through config file, not set through CLI, use default
        config["mqtt_port"] = DEFAULTS["mqtt_port"]

    if args.mqtt_client_id:
        config["mqtt_client_id"] = args.mqtt_client_id
    elif "mqtt_client_id" not in config:
        # Not set through config file, not set through CLI, use default
        config["mqtt_client_id"] = DEFAULTS["mqtt_client_id"]

    if args.buffer_size:
        config["buffer_size"] = args.buffer_size
    elif "buffer_size" not in config:
        # Not set through config file, not set through CLI, use default
        config["buffer_size"] = DEFAULTS["buffer_size"]

    if args.gpiochip:
        config["gpiochip"] = args.gpiochip

    if args.line:
        config["line"] = args.line

    if args.serial:
        config["serial"] = args.serial

    if args.http_host:
        config["http_host"] = args.http_host
    elif "http_host" not in config:
        # Not set through config file, not set through CLI, use default
        config["http_host"] = DEFAULTS["http_host"]

    if args.http_port:
        config["http_port"] = args.http_port
    elif "http_port" not in config:
        # Not set through config file, not set through CLI, use default
        config["http_port"] = DEFAULTS["http_port"]

    if args.counter_file:
        config["counter_file"] = args.counter_file
    elif "counter_file" not in config:
        # Not set through config file, not set through CLI, use default
        config["counter_file"] = DEFAULTS["counter_file"]

    LOGGER.debug("Completed config: %s", config)

    if "mqtt_host" not in config:
        LOGGER.error("No MQTT host given")
        raise SystemExit(1)

    if "gpiochip" not in config:
        LOGGER.error("No GPIO chip given")
        raise SystemExit(1)

    if "line" not in config:
        LOGGER.error("No GPIO line given")
        raise SystemExit(1)

    if "serial" not in config:
        LOGGER.error("No serial number given")
        raise SystemExit(1)

    water_mqtt_queue: multiprocessing.Queue = multiprocessing.Queue(
        maxsize=config["buffer_size"]
    )

    # Shared variable for the current counter
    counter = multiprocessing.Value("L")

    # Try to read a previously saved counter value
    load_counter(config, counter)
    with counter.get_lock():
        last_written_value = counter.value

    # Only continue if the counter value is not 0, to prevent incorrect
    # values being written to MQTT. The non-0 value can come either from
    # the load_counter call above, or the http process
    procs: List[multiprocessing.Process] = []

    http_proc = multiprocessing.Process(
        target=http_main, name="http", args=(counter, config)
    )
    http_proc.start()
    procs.append(http_proc)

    LOGGER.info("Waiting for counter to be non 0")
    while True:
        with counter.get_lock():
            if counter.value > 0:
                break

        time.sleep(1)

    gpio_proc = multiprocessing.Process(
        target=gpio_main, name="water", args=(counter, water_mqtt_queue, config)
    )
    gpio_proc.start()
    procs.append(gpio_proc)

    mqtt_proc = multiprocessing.Process(
        target=mqtt_main, name="mqtt", args=(water_mqtt_queue, config)
    )
    mqtt_proc.start()
    procs.append(mqtt_proc)

    # Wait forever for one of the processes to die. If that happens,
    # kill the whole program.
    #
    # Also, write the current counter value to a file every 60
    # seconds, if it has changed.
    run = True

    last_written_time = 0.0
    while run:
        try:
            for proc in procs:
                if not proc.is_alive():
                    LOGGER.error(
                        "Child process %s died, terminating program", proc.name
                    )
                    run = False

            time.sleep(1)
            if last_written_time < time.time() - 60:
                last_written_time = time.time()

                with counter.get_lock():
                    current_counter = counter.value

                if current_counter == 0:
                    # Not set yet, ignore
                    LOGGER.debug("Counter is 0, not writing")
                    continue

                if current_counter == last_written_value:
                    LOGGER.debug("Counter has not changed, not writing")
                    continue

                write_counter(config, current_counter)

        except KeyboardInterrupt:
            LOGGER.info("Caught keyboard interrupt, exiting")
            run = False

    for proc in procs:
        LOGGER.debug("Terminating %s", proc.name)
        proc.terminate()

    with counter.get_lock():
        write_counter(config, counter.value)
    raise SystemExit(1)
