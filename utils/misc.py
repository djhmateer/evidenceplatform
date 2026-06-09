import json
import os
import platform
import psutil
import re
import socket
import sys
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


def get_ip_country(ip: Optional[str] = None) -> Optional[str]:
    """Return the ISO 3166-1 alpha-2 country code for an IP via ip-api.com.

    Looks up the caller's own public IP when `ip` is None. Returns None if the
    lookup fails for any reason (no network, rate limited, etc.) so callers can
    decide how to treat an inconclusive result.
    """
    try:
        target = ip or ""
        url = f"http://ip-api.com/json/{target}?fields=status,countryCode"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        if data.get("status") != "success":
            return None
        return data.get("countryCode")
    except Exception:
        return None


def ensure_vpn_connection(my_public_ip: Optional[str] = None) -> None:
    """Warn (and offer to abort) if the public IP is in the operator's home country.

    This is a VPN sanity check: set HOME_COUNTRY in .env to your own ISO country
    code (e.g. "IL", "US") and connect your VPN to a *different* country before
    archiving. If the public IP still geolocates to HOME_COUNTRY, the operator is
    almost certainly not on the VPN and their personal IP would be recorded in the
    archive metadata.

    No-op when HOME_COUNTRY is unset, so the check is opt-in. An inconclusive
    geo lookup (None) is treated as "can't confirm" and prompts the operator
    rather than silently proceeding or aborting.
    """
    home_country = os.getenv("HOME_COUNTRY", "").strip().upper()
    if not home_country:
        return

    detected_country = get_ip_country(my_public_ip)

    if detected_country is None:
        message = (
            "Could not determine your public IP's country to verify the VPN "
            "connection."
        )
    elif detected_country == home_country:
        message = (
            f"Your public IP appears to be in your home country ({home_country}). "
            "You may NOT be connected to a VPN — your personal IP would be recorded "
            "in the archive metadata."
        )
    else:
        # Public IP is in a country other than home -> VPN looks active.
        print(f"VPN check passed: public IP geolocates to {detected_country} "
              f"(home country is {home_country}).")
        return

    print(f"WARNING: {message}")
    proceed = input("Are you sure you want to proceed? (yes/no): ").strip().lower()
    if proceed not in {"yes", "y"}:
        print("Exiting...")
        sys.exit(0)


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