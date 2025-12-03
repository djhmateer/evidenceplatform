import hashlib
import os
import subprocess
from pathlib import Path
from typing import Optional

import requests
from pyasn1.codec.der import encoder
from pydantic import BaseModel
from rfc3161ng import RemoteTimestamper

from utils import ROOT_DIR


class TsaCertsLocation(BaseModel):
    tsa_cert: Path
    ca_cert: Path

def get_tsa_certs() -> TsaCertsLocation:
    tsa_certs_dir = Path(ROOT_DIR) / "tsa_certs"
    if not tsa_certs_dir.exists():
        tsa_certs_dir.mkdir()
        print(f"Created directory: {tsa_certs_dir}")
    # Download the TSA certificate and CA certificate if they are not present
    tsa_cert_url = "https://freetsa.org/files/tsa.crt"
    ca_cert_url = "https://freetsa.org/files/cacert.pem"
    tsa_cert_path = tsa_certs_dir / "tsa.crt"
    ca_cert_path = tsa_certs_dir / "cacert.pem"
    if not tsa_cert_path.exists():
        print(f"Downloading TSA certificate from {tsa_cert_url}...")
        try:
            import requests
            response = requests.get(tsa_cert_url)
            response.raise_for_status()
            with open(tsa_cert_path, "wb") as f:
                f.write(response.content)
            print(f"Downloaded TSA certificate to {tsa_cert_path}")
        except Exception as e:
            print(f"Failed to download TSA certificate: {e}")
    if not ca_cert_path.exists():
        print(f"Downloading CA certificate from {ca_cert_url}...")
        try:
            import requests
            response = requests.get(ca_cert_url)
            response.raise_for_status()
            with open(ca_cert_path, "wb") as f:
                f.write(response.content)
            print(f"Downloaded CA certificate to {ca_cert_path}")
        except Exception as e:
            print(f"Failed to download CA certificate: {e}")
    return TsaCertsLocation(tsa_cert=tsa_cert_path, ca_cert=ca_cert_path)


def ensure_openssl_on_path():
    openssl_exe_exists = False
    openssl_dir = None
    has_stored_path = Path("open_ssl_location.txt").exists()
    if has_stored_path:
        with open("open_ssl_location.txt", "r", encoding="utf-8") as f:
            open_ssl_containing_dir = f.read().strip()
        openssl_dir = Path(open_ssl_containing_dir)
        openssl_exe = openssl_dir / "openssl.exe"
        openssl_exe_exists = openssl_exe.exists()

    if not openssl_exe_exists:
        if has_stored_path:
            print("OpenSSL not found in the expected directory. Downloading prebuilt OpenSSL for Windows... (this may take a while)")
        else:
            print("No OpenSSL installation found.")
        print("In order to verify that an archiving session occurred at a specific point in time, you need to have a program called OpenSSL installed.")
        download_installer = input("Would you like us to install OpenSSL for you? (y/n): ").strip().lower()
        if download_installer == "y":
            url = "https://download.firedaemon.com/FireDaemon-OpenSSL/FireDaemon-OpenSSL-x64-3.5.0.exe"
            installer_path = Path("Win64OpenSSL.exe")
            print("Downloading OpenSSL installer... (this may take a while)")
            installer_data = requests.get(url)
            installer_data.raise_for_status()
            with open(installer_path, "wb") as f:
                f.write(installer_data.content)

            print("We've downloaded the OpenSSL installer. Please run it to install OpenSSL, and make sure to add it to the PATH variable.")
            input("Press Enter to start the OpenSSL installation.")
            subprocess.run([installer_path], check=True)
            print("OpenSSL installation complete.")
        open_ssl_location = input("Input the directory where OpenSSL was installed (e.g., C:\\OpenSSL-Win64): ")
        openssl_dir = Path(open_ssl_location) / "bin"
        with open("open_ssl_location.txt", "w", encoding="utf-8") as f:
            f.write(str(openssl_dir))
        ensure_openssl_on_path()
        return

    # Add to PATH for current process
    os.environ["PATH"] = str(openssl_dir) + os.pathsep + os.environ["PATH"]



def hash_file(filepath:Path):
    with open(filepath, "rb") as f:
        return hashlib.sha256(f.read()).digest()

TSA_URL= "https://freetsa.org/tsr"

def timestamp_file(filepath:Path):
    with open(filepath, "rb") as f:
        data = f.read()

    certificate_paths = get_tsa_certs()

    with open(certificate_paths.tsa_cert, "rb") as f:
        tsa_cert = f.read()

    timestamper = RemoteTimestamper('https://freetsa.org/tsr', certificate=tsa_cert)
    tsr = timestamper(data=data, return_tsr=True)

    tsr_path = filepath.with_suffix(filepath.suffix + ".tsr")

    with open(tsr_path, "wb") as f:
        f.write(encoder.encode(tsr))


    print(f"✅ Timestamp response saved to {tsr_path}")
    print(f"📅 You can verify this later using OpenSSL or any RFC3161 tool.")


def verify_timestamp(
    data_file: Path,
    tsr_file: Optional[Path] = None,
):
    if tsr_file is None:
        data_file.with_suffix(data_file.suffix + ".tsr")
    # Normalize all paths
    certificate_paths = get_tsa_certs()
    data_file = str(Path(data_file).resolve())
    tsr_file = str(Path(tsr_file).resolve())
    ca_cert_file = str(certificate_paths.ca_cert)
    tsa_cert_file = str(certificate_paths.tsa_cert)

    # Add OpenSSL bin directory to PATH
    ensure_openssl_on_path()

    # Construct OpenSSL verification command
    cmd = [
        "openssl", "ts", "-verify",
        "-data", data_file,
        "-in", tsr_file,
        "-CAfile", ca_cert_file,
        "-untrusted", tsa_cert_file,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        print("✅ Timestamp verification successful!")
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print("❌ Timestamp verification failed!")
        print("STDOUT:", e.stdout)
        print("STDERR:", e.stderr)



def interactive_timestamp_ui():
    mode = input("would you like to timestamp a file (t) or verify a timestamp (v)? ")
    if mode.lower() == 't':
        file_path = input("Enter the path to the file you want to timestamp: ")
        timestamp_file(Path(file_path))
    elif mode.lower() == 'v':
        data_file = Path(input("Enter the path to the data file: "))
        tsr_file = Path(data_file).with_suffix(data_file.suffix + ".tsr")
        if not tsr_file.exists():
            tsr_file = Path(input("Enter the path to the timestamp response file (.tsr): "))
        verify_timestamp(data_file, Path(tsr_file))
    else:
        print("Invalid option. Please enter 't' for timestamping or 'v' for verification.")

def test_timestamping():
    certificate_paths = get_tsa_certs()
    with open(certificate_paths.tsa_cert, "rb") as f:
        tsa_cert = f.read()
    timestamper = RemoteTimestamper('https://freetsa.org/tsr', certificate=tsa_cert)
    tsr = timestamper(data=b"data", return_tsr=True)


# Usage example
if __name__ == "__main__":
    # test_timestamping()
    interactive_timestamp_ui()

