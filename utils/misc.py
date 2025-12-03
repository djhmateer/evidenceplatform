import json
import platform
import psutil
import re
import socket
import uuid
from typing import Optional

import requests


def get_my_private_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Connect to a public IP, doesn't have to be reachable
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def get_my_public_ip():
    try:
        response = requests.get('https://api.ipify.org?format=text', timeout=5)
        response.raise_for_status()
        return response.text.strip()
    except Exception:
        return '0.0.0.0'


def get_system_info() -> Optional[str]:
    try:
        info = dict()
        info['platform']=platform.system()
        info['platform-release']=platform.release()
        info['platform-version']=platform.version()
        info['architecture']=platform.machine()
        info['hostname']=socket.gethostname()
        info['ip-address']=socket.gethostbyname(socket.gethostname())
        info['mac-address']=':'.join(re.findall('..', '%012x' % uuid.getnode()))
        info['processor']=platform.processor()
        info['ram']=str(round(psutil.virtual_memory().total / (1024.0 **3)))+" GB"
        return json.dumps(info)
    except Exception as e:
        print(str(e))
        return None


if __name__ == "__main__":
    print(get_system_info)