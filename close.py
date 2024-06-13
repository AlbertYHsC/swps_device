import pathlib
import time
from lib.utils import modify_tmp_file

tmpPath = pathlib.Path('./ModifyMeToClose.tmp')

tmp = modify_tmp_file(tmpPath)

time.sleep(10)

if tmpPath.is_file():
    tmpPath.unlink()
