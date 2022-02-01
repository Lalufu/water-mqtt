"""
TODO: replace
"""

import logging

from flask import Flask, request
from gunicorn.app.base import BaseApplication

LOGGER = logging.getLogger(__name__)
APP = Flask(__name__)
COUNTER = None


class StandaloneApplication(BaseApplication):
    def __init__(self, app, options=None):
        self.options = options or {}
        self.application = app
        super().__init__()

    def load_config(self):
        config = {
            key: value
            for key, value in self.options.items()
            if key in self.cfg.settings and value is not None
        }
        for key, value in config.items():
            self.cfg.set(key.lower(), value)

    def load(self):
        return self.application


@APP.route("/counter/get", methods=["GET"])
def handle_counter_get():
    """
    Handle a call to the /counter/get endpoint
    """

    global COUNTER

    with COUNTER.get_lock():
        counter = COUNTER.value

    return f"{counter}\n", 200


@APP.route("/counter/set", methods=["POST"])
def handle_counter_set():
    """
    Handle a call to the /counter/set endpoint
    """

    global COUNTER

    # The value to be set is the first key in the list of
    # values passed in the post
    keys = list(request.form.keys())
    if len(keys) < 1:
        return "No value given\n", 400

    try:
        new_counter = int(keys[0])
    except Exception:
        return "Not an integer\n", 400

    if new_counter < 0:
        return "Must be positive\n", 400

    LOGGER.info("Setting counter to %d", new_counter)
    with COUNTER.get_lock():
        COUNTER.value = new_counter

    return "OK\n", 200


def http_main(counter, config):
    """
    Main function for the http subprocess
    """

    LOGGER.info("http process starting")

    global COUNTER
    COUNTER = counter

    options = {
        "bind": f"{config['http_host']}:{config['http_port']}",
        "workers": 1,
    }
    StandaloneApplication(APP, options).run()
