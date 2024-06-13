import configparser
import logging
import queue
import threading
import time

import mysql.connector

from lib.settings import cfgPath, tmpPath, closeEvent, lock_edges, edges
from lib.swps import local, server
from lib.utils import create_config_file, create_tmp_file

if __name__ == '__main__':
    if not cfgPath.is_file():
        create_config_file(cfgPath)

    tmp = create_tmp_file(tmpPath)

    cfg = configparser.ConfigParser()
    cfg.read(cfgPath, encoding='utf-8')

    logger = logging.getLogger('root')
    logger.setLevel(logging.INFO)
    ch = logging.StreamHandler()
    fh = logging.FileHandler(
        filename=cfg['Default']['log_path'],
        mode='a',
        encoding='utf-8'
    )

    ch.setLevel(logging.INFO)
    fh.setLevel(logging.INFO)
    formatter = logging.Formatter(
        '%(asctime)s | %(name)s | %(levelname)s : %(message)s'
    )

    ch.setFormatter(formatter)
    fh.setFormatter(formatter)
    logger.addHandler(ch)
    logger.addHandler(fh)

    dbconfig = {
        'host': cfg['SQL']['host'],
        'port': int(cfg['SQL']['port']),
        'user': cfg['SQL']['user'],
        'password': cfg['SQL']['password'],
        'database': cfg['SQL']['database']
    }

    cnxpool = mysql.connector.pooling.MySQLConnectionPool(
        pool_name='swps_sql_pool',
        pool_size=int(cfg['Default']['max_client_devices'])+1,
        **dbconfig
    )

    syst_list = []

    t = threading.Thread(
        target=local.run_swps_local_sys,
        args=(cfg, cnxpool.get_connection(), logger)
    )
    lock_edges.acquire()
    edges[cfg['Default']['device_sn']] = True
    lock_edges.release()
    syst_list.append(t)
    t.start()

    t = threading.Thread(
        target=server.listen_serial_port,
        args=(cfg, )
    )
    syst_list.append(t)
    t.start()

    queue_main = queue.Queue()
    lock_main = threading.Lock()

    t = threading.Thread(
        target=server.listen_edge_clients,
        args=(cfg, queue_main, lock_main)
    )
    syst_list.append(t)
    t.start()

    t = threading.Thread(
        target=server.listen_web_clients,
        args=(cfg, queue_main, lock_main)
    )
    syst_list.append(t)
    t.start()

    while bool(tmp['Default']['not_close']):
        try:
            with open(tmpPath, 'r', encoding='utf-8') as f:
                tmp.read_file(f)

        except BaseException as err:
            logger.error(f'Failed to read tmp file! Error: {err!r}')
            break

        err = None
        clients = []
        if lock_main.acquire(timeout=float(cfg['Default']['server_timeout(sec.)'])):
            while not queue_main.empty():
                try:
                    c = queue_main.get(timeout=float(cfg['Default']['server_timeout(sec.)']))
                    clients.append(c)

                except BaseException as err:
                    err = f'Failed to get client from queue! Error: {err!r}'

            lock_main.release()

        if clients:
            for c in clients:
                if c[2]:
                    t = threading.Thread(
                        target=server.handle_edge_sys,
                        args=(c[0], c[1], cfg, cnxpool.get_connection(), logger)
                    )
                    syst_list.append(t)
                    t.start()

                else:
                    t = threading.Thread(
                        target=server.handle_web_client,
                        args=(c[0], c[1], cfg, logger)
                    )
                    t.start()

        if err:
            logger.warning(err)

    closeEvent.set()

    for t in syst_list:
        t.join(timeout=10)
        if t.is_alive():
            logger.error('Failed to stop thread!')

    logger.info('Close program.')

    time.sleep(2)
    tmpPath.unlink()
