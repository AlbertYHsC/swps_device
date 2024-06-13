import json
import logging
import queue
import socket
import threading
import time
from configparser import ConfigParser
from datetime import datetime
from typing import Tuple, Dict

import mysql.connector
import serial
from serial.tools import list_ports

from lib.settings import closeEvent, lock_edges, lock_ser, edges, ser_edges
from lib.utils import key2head, create_data_dict


def listen_serial_port(
    cfg: ConfigParser
) -> None:
    while not closeEvent.is_set():
        ports = list_ports.comports()
        ports = [i.device for i in ports if cfg['Edge']['arduino_uno_r4_wifi'] in i.hwid]

        lock_ser.acquire()
        ser_edges[:] = ports[:].copy()
        lock_ser.release()


def listen_edge_clients(
    cfg: ConfigParser,
    q: queue.Queue,
    l: threading.Lock,
    logger_parent: logging.Logger = None
) -> None:
    server_sys = SmartWaterPumpServer(
        cfg['Default']['server_ip'],
        int(cfg['Default']['server_port']),
        int(cfg['Default']['max_client_devices']),
        float(cfg['Default']['server_timeout(sec.)']),
        True,
        logger_parent
    )

    while not closeEvent.is_set():
        server_sys.run(q, l)

    server_sys.close()


def listen_web_clients(
    cfg: ConfigParser,
    q: queue.Queue,
    l: threading.Lock,
    logger_parent: logging.Logger = None
) -> None:
    server_sys = SmartWaterPumpServer(
        'localhost',
        int(cfg['Default']['web_port']),
        int(cfg['Default']['max_web_clients']),
        float(cfg['Default']['server_timeout(sec.)']),
        False,
        logger_parent
    )

    while not closeEvent.is_set():
        server_sys.run(q, l)

    server_sys.close()


def handle_edge_sys(
    client: socket.socket,
    address: Tuple,
    cfg: ConfigParser,
    cnx: mysql.connector.pooling.PooledMySQLConnection,
    logger_parent: logging.Logger = None
) -> None:
    server_sys = SmartWaterPumpMiddleware(client, address, cfg, cnx, logger_parent)

    while (not closeEvent.is_set()) and server_sys.keep_server:
        server_sys.run()

    server_sys.close()


def handle_web_client(
    client: socket.socket,
    address: Tuple,
    cfg: ConfigParser,
    logger_parent: logging.Logger = None
) -> None:
    server_sys = WebClientMiddleware(client, address, cfg, logger_parent)

    server_sys.run()

    time.sleep(10)

    server_sys.close()


class SmartWaterPumpServer:
    def __init__(
        self,
        address: str,
        port: int,
        max_clients_num: int,
        timeout: float,
        is_edge: bool,
        logger_parent: logging.Logger = None
    ) -> None:
        """Server system to listen client devices.

        :param address: server name or ip
        :param port: server port
        :param max_clients_num: maximum number of clients connected simultaneously
        :param timeout: server timeout
        :param is_edge: client type (device or web)
        :param logger_parent: to get parent logger information
        """
        if logger_parent:
            self.logger = logging.getLogger(
                logger_parent.name + '.' + self.__class__.__name__
            )

        else:
            self.logger = logging.getLogger(self.__class__.__name__)

        self.is_edge = is_edge

        self.ss = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.ss.bind((address, port))
        self.ss.listen(max_clients_num)
        self.ss.settimeout(timeout)

    def run(self, q: queue.Queue, lock_q: threading.Lock) -> None:
        try:
            client, addr = self.ss.accept()

            lock_q.acquire()
            q.put((client, addr, self.is_edge))
            lock_q.release()

        except BaseException as err:
            client_type = 'client device' if self.is_edge else 'web client'
            self.logger.debug(f'Failed to handle {client_type}! Error: {err!r}')

    def close(self) -> None:
        self.ss.shutdown(socket.SHUT_RDWR)
        self.ss.close()


class SmartWaterPumpMiddleware:
    def __init__(
        self,
        client: socket.socket,
        address: Tuple,
        cfg: ConfigParser,
        cnx: mysql.connector.pooling.PooledMySQLConnection,
        logger_parent: logging.Logger = None
    ) -> None:
        """Server system to handle client device communication.

        :param client: client device connection
        :param address: client device network information
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

        self.client = client
        self.address = address
        self.cfg = cfg
        self.cnx = cnx
        self.device_sn = ''
        self.keep_server = True

        self.logger.info(f'Connected by client device {self.address[0]}[{self.address[1]}].')

    def _setup_edge(self, device_sn: str) -> Dict:
        self.device_sn = device_sn

        lock_edges.acquire()
        edges[device_sn] = True
        lock_edges.release()

        data = create_data_dict('', True, {})

        return data

    def _set_params(self) -> Dict:
        cursor = self.cnx.cursor(dictionary=True)

        query = ("SELECT DetectInterval, PumpStartTime, SoilMoisture "
                 "FROM EdgeDevices "
                 "WHERE DeviceSN = %s")

        cursor.execute(query, (self.device_sn, ))

        data = cursor.fetchone()

        if data is None:
            data = {
                'DetectInterval': int(self.cfg['Local']['detect_interval(min.)']),
                'PumpStartTime': int(float(self.cfg['Local']['pump_start_time(sec.)']) * 1000),
                'SoilMoisture': int(self.cfg['Local']['keep_soil_moisture'])
            }
        else:
            data['PumpStartTime'] = int(data['PumpStartTime'] * 1000)

        data['RTCTime'] = time.time()
        data = create_data_dict('', True, data)

        return data

    def _upload_sensor_record(self, data: Dict) -> Dict:
        cursor = self.cnx.cursor()

        add_record = ("INSERT INTO SensorRecords "
                      "(UserID, DeviceId, Temperature, Humidity, Pressure, RawValue0, RawValue1, RawValue2, "
                      "RawValue3, Voltage0, Voltage1, Voltage2, Voltage3, DetectTime, PumpStartTime) "
                      "VALUES ((SELECT UserId FROM EdgeDevices WHERE DeviceSN = %s), "
                      "(SELECT Id FROM EdgeDevices WHERE DeviceSN = %s), "
                      "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)")
        data_record = (
            data['DeviceSN'],
            data['DeviceSN'],
            data['Temperature'],
            data['Humidity'],
            data['Pressure'],
            data['RawValue0'],
            data['RawValue1'],
            data['RawValue2'],
            data['RawValue3'],
            data['Voltage0'],
            data['Voltage1'],
            data['Voltage2'],
            data['Voltage3'],
            datetime.fromtimestamp(data['DetectTime']),
            data['PumpStartTime'] / 1000
        )
        cursor.execute(add_record, data_record)

        self.cnx.commit()
        cursor.close()

        data = create_data_dict('', True, {})

        return data

    def close(self) -> None:
        self.cnx.close()
        self.client.shutdown(socket.SHUT_RDWR)
        self.client.close()

        lock_edges.acquire()
        edges[self.device_sn] = False
        lock_edges.release()

    def run(self) -> None:
        try:
            data = self.client.recv(int(self.cfg['Default']['max_bufsize']))
            data = data.decode(self.cfg['Default']['sys_encoding'])
            data = json.loads(data)

            try:
                if data['Api'] == 'setup_edge':
                    data = self._setup_edge(data['Data']['DeviceSN'])

                elif data['Api'] == 'set_params':
                    data = self._set_params()

                elif data['Api'] == 'upload_sensor_record':
                    data = self._upload_sensor_record(data['Data'])

                else:
                    self.logger.warning(f'Received unknown message {data}!')
                    data = create_data_dict('', False, {})

            except BaseException as err:
                err = f'Unable to handle client device request! Error: {err!r}'
                self.logger.warning(err)
                self.keep_server = False
                data = create_data_dict('', False, {})

            data = json.dumps(data).encode(self.cfg['Default']['sys_encoding'])
            self.client.send(data)

        except BaseException as err:
            err = f'Client Device {self.address[0]}[{self.address[1]}] disconnected unexpectedly! Error: {err!r}'
            self.logger.warning(err)
            self.keep_server = False


class WebClientMiddleware:
    def __init__(
            self,
            client: socket.socket,
            address: Tuple,
            cfg: ConfigParser,
            logger_parent: logging.Logger = None
    ) -> None:
        """Server system to handle client device communication.

        :param client: client device connection
        :param address: client device network information
        :param cfg: system setting
        :param logger_parent: to get parent logger information
        """
        if logger_parent:
            self.logger = logging.getLogger(
                logger_parent.name + '.' + self.__class__.__name__
            )

        else:
            self.logger = logging.getLogger(self.__class__.__name__)

        self.client = client
        self.address = address
        self.cfg = cfg

        self.logger.info(f'Connected by web client {self.address[0]}[{self.address[1]}].')

    def _get_edges(self) -> Dict:
        data = {
            'Clients': [],
            'ServerSN': self.cfg['Default']['device_sn'],
            'ServerStatus': True
        }
        lock_edges.acquire()
        edges_c = edges.copy()
        lock_edges.release()

        for k, v in edges_c.items():
            data['Clients'].append({
                'DeviceSN': k,
                'Status': v,
                'Registered': False
            })

        edges_s = []
        lock_ser.acquire()

        for p in ser_edges:
            ser = serial.Serial()
            ser.baudrate = 115200
            ser.port = p
            ser.timeout = 1
            ser.write_timeout = 1

            data_ser = create_data_dict('get_device_sn', False, {})
            data_ser = json.dumps(data_ser)
            data_ser = data_ser.encode(self.cfg['Default']['sys_encoding'])

            try:
                ser.open()
                ser.write(data_ser)

                time.sleep(0.1)

                data_ser = ser.readline()
                ser.close()

            except BaseException as err:
                self.logger.warning(f'Failed to open serial port {p}! Error: {err!r}')
                data_ser = None
                if ser.is_open:
                    ser.close()

            if data_ser:
                data_ser = data_ser.decode(self.cfg['Default']['sys_encoding'])
                data_ser = json.loads(data_ser)

                try:
                    if data_ser['Result']:
                        edges_s.append(data_ser['Data']['DeviceSN'])

                except BaseException as err:
                    self.logger.warning(f'Failed to get deviceSN from serial port {p}! Error: {err!r}')

        lock_ser.release()

        lock_edges.acquire()

        for sn in edges_s:
            if sn not in edges_c.keys():
                data['Clients'].append({
                    'DeviceSN': sn,
                    'Status': True,
                    'Registered': False
                })

        lock_edges.release()

        data = create_data_dict('', True, data)

        return data

    def _reset_wifi(self, data: Dict) -> Dict:
        data_ser = {
            'DeviceSN': data['DeviceSN'],
            'Ssid': data['WiFiSsid'],
            'Password': data['WiFiPassword'],
            'ServerIP': self.cfg['Default']['server_ip'],
            'ServerPort': self.cfg['Default']['server_port']
        }
        data_ser = create_data_dict('reset_wifi', False, data_ser)
        data_ser = json.dumps(data_ser)
        data_ser = data_ser.encode(self.cfg['Default']['sys_encoding'])

        result = True

        lock_ser.acquire()

        for p in ser_edges:
            ser = serial.Serial()
            ser.baudrate = 115200
            ser.port = p
            ser.timeout = 1
            ser.write_timeout = 1

            try:
                ser.open()
                ser.write(data_ser)
                time.sleep(0.1)
                ser.close()

            except BaseException as err:
                self.logger.warning(f'Failed to open serial port {p}! Error: {err!r}')
                result = False
                if ser.is_open:
                    ser.close()

                break

        lock_ser.release()

        data = create_data_dict('', result, {})

        return data

    def close(self) -> None:
        self.client.shutdown(socket.SHUT_RDWR)
        self.client.close()

    def run(self) -> None:
        try:
            data = self.client.recv(int(self.cfg['Default']['max_bufsize']))
            data = data.decode(self.cfg['Default']['sys_encoding'])
            data = json.loads(data)

            try:
                if data['Api'] == 'get_edges':
                    data = self._get_edges()

                elif data['Api'] == 'reset_wifi':
                    data = self._reset_wifi(data['Data'])

                else:
                    self.logger.warning(f'Received unknown message {data}!')
                    data = create_data_dict('', False, {})

            except BaseException as err:
                err = f'Unable to handle web client request! Error: {err!r}'
                self.logger.warning(err)
                data = create_data_dict('', False, {})

            data = json.dumps(data).encode(self.cfg['Default']['sys_encoding'])
            self.client.send(data)

        except BaseException as err:
            err = f'Web client {self.address[0]}[{self.address[1]}] disconnected unexpectedly! Error: {err!r}'
            self.logger.warning(err)
