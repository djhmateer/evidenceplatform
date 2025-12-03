# Download and extract ffmpeg if not present, and add to PATH
import os
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional


def find_ffmpeg_executable_in_dir(ffmpeg_dir: Path)->Optional[Path]:
    # Find the actual ffmpeg.exe path inside the extracted directory
    if os.path.isdir(ffmpeg_dir):
        for root, dirs, files in os.walk(ffmpeg_dir):
            if "ffmpeg.exe" in files:
                ffmpeg_exe = os.path.join(root, "ffmpeg.exe")
                return Path(ffmpeg_exe)
    return None



def ensure_ffmpeg_installed():
    print("Ensuring FFMPEG is installed...")
    # Check if ffmpeg is accessible by trying to run it
    ffmpeg_check = os.system("ffmpeg -version >nul 2>&1")
    if ffmpeg_check == 0:
        print("ffmpeg is already installed and accessible.")
        return
    ffmpeg_dir = os.path.join(os.getcwd(), "ffmpeg")
    ffmpeg_exe = find_ffmpeg_executable_in_dir(Path(ffmpeg_dir))
    if ffmpeg_exe:
        ffmpeg_exe_containing_dir = ffmpeg_exe.parent
        os.environ["PATH"] = str(ffmpeg_exe_containing_dir) + os.pathsep + os.environ.get("PATH", "")
        print("local installation of ffmpeg found and added to PATH.")
        return
    # Download ffmpeg if not found
    print("ffmpeg not found, downloading... (this may take a while)")
    ffmpeg_url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    ffmpeg_zip = os.path.join(os.getcwd(), "ffmpeg.zip")
    urllib.request.urlretrieve(ffmpeg_url, ffmpeg_zip)
    with zipfile.ZipFile(ffmpeg_zip, 'r') as zip_ref:
        zip_ref.extractall(ffmpeg_dir)
    os.remove(ffmpeg_zip)
    ffmpeg_exe = find_ffmpeg_executable_in_dir(Path(ffmpeg_dir))
    if ffmpeg_exe:
        ffmpeg_exe_containing_dir = ffmpeg_exe.parent
        os.environ["PATH"] = str(ffmpeg_exe_containing_dir) + os.pathsep + os.environ.get("PATH", "")
        print("ffmpeg downloaded and installed successfully.")
    else:
        raise Exception("ffmpeg could not be installed.")

if __name__ == "__main__":
    ensure_ffmpeg_installed()