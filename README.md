# Water-MQTT gateway

This is a simple application that reads GPIO pin changes, and interprets
these as events coming from a water meter. It keeps track of the current
counter value and sends it to an MQTT gateway.

The application has no sense of the scale that the water meter operates
on, all it does is increase a counter by 1 every time the GPIO pin
changes state to low. It's up to the user to interpret the number properly.

This project uses the kernel [gpiod bindings](https://git.kernel.org/pub/scm/libs/libgpiod/libgpiod.git/)
to communicate with the GPIO subsystem. This library is a bit weird in the
sense that it is not available via pypi, but is very likely provided
by your OS.

All other dependencies can be installed from pypi.

## Installation

This project uses [Poetry](https://python-poetry.org/) for dependency
management, and it's probably easiest to use this, Executing `poetry install 
--no-dev` followed by `poetry run water-mqtt` from the git checkout root should
set up a venv, install the required dependencies into a venv and run
the main program.

Installation via pip into a venv is also possible with `pip install .` from
the git checkout root. This will also create the executable scripts in the
`bin` dir of the venv.

In case you want to do things manually, the main entry point into
the program is `water_mqtt/cli.py:water_mqtt()`.

## Running

`--config`
: Specify a configuration file to load. See the section `Configuration file`
  for details on the syntax. Command line options given in addition to the
  config file override settings in the config file.

`--mqtt-host`
: The MQTT host name to connect to. This is a required parameter.

  Config file: Section `general`, `mqtt-host`

`--mqtt-port`
: The MQTT port number to connect to. Defaults to 1883.

  Config file: Section `general`, `mqtt-port`

`--buffer-size`
: The size of the buffer (in number of measurements) that can be locally
  saved when the MQTT server is unavailable. The buffer is not persistent,
  and will be lost when the program exits. Defaults to 100000.

  Config file: Section `general`, `buffer-size`

`--mqtt-topic`
: The MQTT topic to publish the information to. This is a string that is put
  through python formatting, and can contain references to the variable `serial`.
  `serial` will contain the serial number of the meter, which
  can be set through the `--serial` command line option.
  The default is `water-mqtt/tele/%(serial)s/SENSOR`.

  Config file: Section `general`, `mqtt-topic`

`--mqtt-client-id`
: The client identifier used when connecting to the MQTT gateway. This needs
  to be unique for all clients connecting to the same gateway, only one
  client can be connected with the same name at a time. The default is
  `water-mqtt-gateway`.

  Config file: Section `general`, `mqtt-client-id`

`--gpiochip`
: The device file of the GPIO interface to use

  Config file: Section `general`, `gpiochip`

`--line`
: The GPIO line to use on the GPIO interface

  Config file: Section `general`, `line`

`--serial`
: The serial number of the water meter. Can be used as a variable in the
  `--mqtt-topic` option, and is also added to every MQTT message

  Config file: Section `general`, `serial`

`--http-host`
: Hostname for the built-in HTTP server (see below) to listen on.
  The default is `localhost`, and changing this is not recommended.

  Config file: Section `general`, `http-host`

`--http-port`
: Port for the built-in HTTP server (see below) to listen on.
  The default is `5000`.

  Config file: Section `general`, `http-port`

`--counter-file`
: File to use as storage for the counter value. The application will
  read this file on startup to initialize the counter, and will write the
  current value every 60 seconds, if the value has changed since the
  last write, and on application shutdown. Not being able to write to this
  file is not fatal.

  Config file: Section `general`, `counter-file`

## Configuration file
The program supports a configuration file to define behaviour. The
configuration file is in .ini file syntax, and can contain multiple sections.
The `[general]` section contains settings that define overall program
behaviour.

### Example configuration file

```
[general]
mqtt-client-id = water-gateway-01
mqtt-host = mqtt.example.com
gpiochip = /dev/gpiochip0
line = 18

```
## Data pushed to MQTT

The application pushes data to MQTT

- when the counter changes
- every 60 seconds if the counter does not change

Each push contains the following fields:

- `water_mqtt_timestamp`: The current UNIX timestamp, in milliseconds
- `counter`: The current counter value
- `debounced`: The number of GPIO events that were debounced
- `serial`: The serial number of the meter, as given through the `--serial`
  CLI option

## HTTP server

The application runs a simple HTTP server to allow setting the counter value.
The HTTP server listens on `localhost:5000` per default, and exposes two
endpoints.

To set the counter to `12345` using `curl`:

`curl -XPOST -d 12345 http://localhost:5000/counter/set`

On success, the endpoint returns the string `OK`.


To get the counter value using `curl`:

`curl http://localhost:5000/counter/get`

On success, the endpoint returns the current counter value.


## Counter value and startup

The application assumes that 0 is not a valid counter value, and will wait on
startup until the value is changed. This can be done through two mechanisms:

- Read a counter value from the file specified with the `--counter-file` CLI
  option
- Have the counter value set through the HTTP interface

Once either of these happen the application will start listening for GPIO
events and send data to MQTT.
