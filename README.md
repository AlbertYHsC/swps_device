# Smart Water Pump System - IoT Server
Automatic plant watering system to handle edge device requirements.

It also can drive sensors and relay without edge device when installed on a Raspberry Pi.

This middleware handles communication for the following programs:
* [Smart Water Pump System - Web UI](https://github.com/AlbertYHsC/swps_web.git)
* [Smart Water Pump System - Arduino](https://github.com/AlbertYHsC/swps_edge.git)

## Installation
1. Install Python virtual environment according to `requirements.txt` file.
2. Replace all `your_SWPS_path` with the actual program folder in `swps.service` file.
3. Copy modified `swps.service` file to `/etc/systemd/system` folder.
4. Replace all `your_python_venv_path` with the Python virtual environment folder in `start.sh` and `close.sh` files.
5. Modify `device_sn` and other empty values in `config.ini` file.
6. Enable and Start `swps.service` using the `systemctl` command.
7. (Optional) Register this device when using Raspberry Pi without edge device.
(For Details, please see [SWPS Web UI](https://github.com/AlbertYHsC/swps_web.git).)

## Dependencies
* [adafruit-circuitpython-ads1x15](https://github.com/adafruit/Adafruit_CircuitPython_ADS1x15.git)
* [adafruit-circuitpython-bme280](https://github.com/adafruit/Adafruit_CircuitPython_BME280.git)
* [mysql-connector-python](https://dev.mysql.com/doc/connector-python/en/)
* [pyserial](https://github.com/pyserial/pyserial.git)

## Hardware
### Necessary
* Raspberry Pi (<a color="blue">Recommended</a>) or other Linux PC
* WiFi router
### Optional (use Raspberry Pi to drive sensors and relay without edge device)
* Adafruit ADS1115
* Adafruit BME280
* Relay control module for Raspberry Pi and a motor
#### Optional Wire Connection
![](./device_optional_circuits.svg)