import csv
import logging
import time
from configparser import ConfigParser
from typing import Tuple, Dict, Any

import adafruit_ads1x15.ads1115 as ads1115
import board
import busio
import digitalio
import mysql.connector
from adafruit_ads1x15.analog_in import AnalogIn
from adafruit_bme280 import basic as adafruit_bme280

from lib.settings import closeEvent
from lib.utils import check_time_to_wake_up, key2head


def run_swps_local_sys(
    cfg: ConfigParser,
    cnx: mysql.connector.pooling.PooledMySQLConnection,
    logger_parent: logging.Logger = None
) -> None:
    local_sys = SmartWaterPumpSystem(cfg, cnx, logger_parent)

    bme_check = hasattr(local_sys.sensor, 'bme280')
    ads_check = hasattr(local_sys.sensor, 'ads')
    wpp_check = hasattr(local_sys.pump, 'water_pump')

    if bme_check and ads_check and wpp_check:
        while not closeEvent.is_set():
            local_sys.run()
            time.sleep(float(cfg['Local']['local_sys_run_period(sec.)']))

    local_sys.close()


class SmartWaterPumpSystem:
    def __init__(
            self,
            cfg: ConfigParser,
            cnx: mysql.connector.pooling.PooledMySQLConnection,
            logger_parent: logging.Logger = None
    ) -> None:
        """Local system to drive water pump.

        :param cfg: system setting
        :param cnx: mysql connection
        :param logger_parent: to get parent logger information
        """
        if logger_parent:
            self.logger = logging.getLogger(
                logger_parent.name + '.' + self.__class__.__name__
            )

        else:
            self.logger = logging.getLogger(self.__class__.__name__)

        self.run_lock = False

        self.cfg = cfg
        self.cnx = cnx
        self.csvPath = cfg['Local']['csv_path']

        self.sensor = SensorAssembly(board.D22, self.logger)
        self.pump = WaterPumpAssembly(board.D23, self.logger)

    def _upload_data_mysql(self, **kwargs) -> None:
        kwargs = key2head(kwargs)

        cursor = self.cnx.cursor()

        add_record = ("INSERT INTO SensorRecords "
                      "(UserID, DeviceId, Temperature, Humidity, Pressure, RawValue0, RawValue1, RawValue2, "
                      "RawValue3, Voltage0, Voltage1, Voltage2, Voltage3, DetectTime, PumpStartTime) "
                      "VALUES ((SELECT UserId, Id FROM EdgeDevices WHERE DeviceSN = %s), "
                      "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)")
        data_record = (
            self.cfg['Default']['device_sn'],
            kwargs['Temperature'],
            kwargs['Humidity'],
            kwargs['Pressure'],
            kwargs['RawValue0'],
            kwargs['RawValue1'],
            kwargs['RawValue2'],
            kwargs['RawValue3'],
            kwargs['Voltage0'],
            kwargs['Voltage1'],
            kwargs['Voltage2'],
            kwargs['Voltage3'],
            kwargs['DetectTime'],
            kwargs['PumpStartTime']
        )
        cursor.execute(add_record, data_record)

        self.cnx.commit()
        cursor.close()

    def _write_data_local(self, **kwargs) -> None:
        head = [
            'Temperature',
            'Humidity',
            'Pressure',
            'RawValue0',
            'RawValue1',
            'RawValue2',
            'RawValue3',
            'Voltage0',
            'Voltage1',
            'Voltage2',
            'Voltage3',
            'DetectTime',
            'PumpStartTime'
        ]

        try:
            with open(
                self.csvPath, 'r', newline='', encoding=self.cfg['Default']['sys_encoding']
            ) as f:
                reader = csv.reader(f, dialect='excel')
                row0 = next(reader)

        except BaseException as err:
            row0 = None
            self.logger.warning(f'Failed to open historical record! Error: {err!r}')

        try:
            with open(
                self.csvPath, 'a', newline='', encoding=self.cfg['Default']['sys_encoding']
            ) as f:
                writer = csv.DictWriter(f, fieldnames=head, dialect='excel')

                if head != row0:
                    writer.writeheader()

                kwargs = key2head(kwargs)
                writer.writerow(kwargs)

        except BaseException as err:
            self.logger.error(f'Record file corrupted! Error: {err!r}')

    def run(self) -> None:
        sleep_time = int(self.cfg['Local']['detect_interval(min.)'])
        run_now, time_now = check_time_to_wake_up(sleep_time)
        if not self.run_lock and run_now:
            temp, hum, press = self.sensor.detect_atmospheric_data()
            data = self.sensor.detect_optional_data()

            if data[3]['raw'] > int(self.cfg['Local']['keep_soil_moisture']):
                start_time = float(self.cfg['Local']['pump_start_time(sec.)'])
                self.pump.start_for_a_while(start_time)

            else:
                start_time = 0.

            try:
                self._upload_data_mysql(
                    temperature=float(temp),
                    humidity=float(hum),
                    pressure=float(press),
                    raw_value0=int(data[0]['raw']),
                    raw_value1=int(data[1]['raw']),
                    raw_value2=int(data[2]['raw']),
                    raw_value3=int(data[3]['raw']),
                    voltage0=float(data[0]['volt']),
                    voltage1=float(data[1]['volt']),
                    voltage2=float(data[2]['volt']),
                    voltage3=float(data[3]['volt']),
                    detect_time=time_now,
                    pump_start_time=float(start_time)
                )

            except BaseException as err:
                self.logger.warning(f'Failed to upload record! Error: {err!r}')

                self._write_data_local(
                    temperature=temp,
                    humidity=hum,
                    pressure=press,
                    raw_value0=data[0]['raw'],
                    raw_value1=data[1]['raw'],
                    raw_value2=data[2]['raw'],
                    raw_value3=data[3]['raw'],
                    voltage0=data[0]['volt'],
                    voltage1=data[1]['volt'],
                    voltage2=data[2]['volt'],
                    voltage3=data[3]['volt'],
                    detect_time=time_now.strftime('%Y-%m-%d %H:%M:%S.%f'),
                    pump_start_time=start_time
                )

            self.run_lock = True

        elif not run_now:
            self.run_lock = False

    def close(self) -> None:
        self.cnx.close()


class SensorAssembly:
    def __init__(
            self,
            spi_cs: Any,
            logger_parent: logging.Logger = None
    ) -> None:
        """Contain BME280 atmospheric sensor and ADS1115 ADC.

        :param spi_cs: SPI chip select pin
        :param logger_parent: to get parent logger information
        """
        if logger_parent:
            self.logger = logging.getLogger(
                logger_parent.name + '.' + self.__class__.__name__
            )

        else:
            self.logger = logging.getLogger(self.__class__.__name__)

        try:
            self.spi = board.SPI()
            self.spi_cs = digitalio.DigitalInOut(spi_cs)
            self.bme280 = adafruit_bme280.Adafruit_BME280_SPI(self.spi, self.spi_cs)
            self.logger.info(f'Success to initialize device(bme280 {spi_cs})!')

        except BaseException as err:
            self.logger.warning(
                f'Failed to initialize local device(bme280 {spi_cs})! Error: {err!r}'
            )

        self.i2c = busio.I2C(board.SCL, board.SDA)

        if self.i2c.try_lock():
            i2c_address = self.i2c.scan()

        else:
            i2c_address = []

        self.i2c.unlock()

        time.sleep(2)

        self.logger.info(f'I2C addresses found: {[hex(i) for i in i2c_address]}')

        for i in i2c_address:
            try:
                self.ads = ads1115.ADS1115(address=i, i2c=self.i2c)
                self.logger.info(f'Success to initialize device(ads1115 {hex(i)})!')
                break

            except BaseException as err:
                self.logger.warning(
                    f'Failed to initialize local device(ads1115 {hex(i)})! Error: {err!r}'
                )

    def detect_atmospheric_data(self) -> Tuple[float, float, float]:
        try:
            temp = self.bme280.temperature
            hum = self.bme280.humidity
            press = self.bme280.pressure

        except BaseException as err:
            temp = -1
            hum = -1
            press = -1

            self.logger.warning(f'Failed to get atmospheric data! Error: {err!r}')

        return temp, hum, press

    def detect_optional_data(self) -> Dict:
        data = {}
        for i in (ads1115.P0, ads1115.P1, ads1115.P2, ads1115.P3):
            try:
                chan = AnalogIn(self.ads, i)
                data[i] = {'raw': chan.value, 'volt': chan.voltage}

            except BaseException as err:
                data[i] = {'raw': -1, 'volt': -1}

                self.logger.warning(
                    f'Failed to get optional analog data(c{i})! Error: {err!r}'
                )

        return data


class WaterPumpAssembly:
    def __init__(
            self,
            wp_pin: Any,
            logger_parent: logging.Logger = None
    ) -> None:
        """Switch relay to control the on/off of the water pump.

        :param wp_pin: water pump control pin
        :param logger_parent: to get parent logger information
        """
        if logger_parent:
            self.logger = logging.getLogger(
                logger_parent.name + '.' + self.__class__.__name__
            )

        else:
            self.logger = logging.getLogger(self.__class__.__name__)

        try:
            self.water_pump = digitalio.DigitalInOut(wp_pin)
            self.water_pump.direction = digitalio.Direction.OUTPUT
            self.logger.info(f'Success to initialize device(water pump {wp_pin})!')

        except BaseException as err:
            self.logger.warning(
                f'Failed to initialize local device(water pump {wp_pin})! Error: {err!r}'
            )

    def start_for_a_while(self, sec: float) -> None:
        try:
            self.water_pump.value = True
            time.sleep(sec)
            self.water_pump.value = False

        except BaseException as err:
            self.logger.warning(f'Failed to start water pump! Error: {err!r}')
