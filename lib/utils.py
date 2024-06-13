from configparser import ConfigParser
from datetime import datetime
from os import PathLike
from typing import Tuple, Dict


def check_time_to_wake_up(sleep_time: int) -> Tuple[bool, datetime]:
    now = datetime.now()
    wake_up = now.minute % sleep_time
    wake_up = not bool(wake_up)

    return wake_up, now


def key2head(kwargs: Dict) -> Dict:
    kwargs_new = {}
    for k, v in kwargs.items():
        k = k.split('_')
        k = [i.capitalize() for i in k]
        k = ''.join(k)
        kwargs_new[k] = v

    return kwargs_new


def create_data_dict(api: str, result: bool, data: Dict) -> Dict:
    dd = {
        'Api': api,
        'Result': int(result),
        'Data': data
    }

    return dd


def create_config_file(cfg_path: str | PathLike[str]) -> None:
    cfg = ConfigParser()
    cfg['Default'] = {
        'device_sn': 'TEST0001',
        'log_path': './system.log',
        'sys_encoding': 'utf-8',
        'server_ip': '',
        'server_port': '',
        'web_port': '',
        'max_bufsize': '2048',
        'max_client_devices': '5',
        'max_web_clients': '20',
        'server_timeout(sec.)': '5'
    }

    cfg['Local'] = {
        'csv_path': './sensors_log.csv',
        'local_sys_run_period(sec.)': '0.2',
        'keep_soil_moisture': '26000',
        'pump_start_time(sec.)': '0.5',
        'detect_interval(min.)': '10'
    }

    cfg['SQL'] = {
        'host': 'localhost',
        'port': '3306',
        'user': '',
        'password': '',
        'database': 'swps_db'
    }

    cfg['Edge'] = {
        'arduino_uno_r4_wifi': 'VID:PID=2341:1002'
    }

    with open(cfg_path, 'w', encoding='utf-8') as f:
        cfg.write(f)


def create_tmp_file(tmp_path: str | PathLike[str]) -> ConfigParser:
    tmp = ConfigParser()
    tmp['Default'] = {'not_close': 'DeleteMeToClose'}

    with open(tmp_path, 'w', encoding='utf-8') as f:
        tmp.write(f)

    return tmp


def modify_tmp_file(tmp_path: str | PathLike[str]) -> ConfigParser:
    tmp = ConfigParser()
    tmp.read(tmp_path, encoding='utf-8')
    tmp['Default']['not_close'] = ''

    with open(tmp_path, 'w', encoding='utf-8') as f:
        tmp.write(f)

    return tmp
