import pathlib
import threading


cfgPath = pathlib.Path('./config.ini')
tmpPath = pathlib.Path('./ModifyMeToClose.tmp')
closeEvent = threading.Event()
lock_edges = threading.Lock()
lock_ser = threading.Lock()
edges = {}
ser_edges = []
