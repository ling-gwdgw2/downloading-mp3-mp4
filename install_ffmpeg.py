import os
import sys
import zipfile
import shutil
import requests

def install_ffmpeg():
    # URL for FFmpeg Windows build (Essentials is smaller and sufficient)
    FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    ZIP_NAME = "ffmpeg.zip"
    EXTRACT_DIR = "ffmpeg_temp"
    BIN_DIR = "bin"

    print(f"Downloading FFmpeg from {FFMPEG_URL}...")
    
    try:
        # Download
        with requests.get(FFMPEG_URL, stream=True) as r:
            r.raise_for_status()
            with open(ZIP_NAME, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        print("Download complete.")

        # Extract
        print("Extracting...")
        with zipfile.ZipFile(ZIP_NAME, 'r') as zip_ref:
            zip_ref.extractall(EXTRACT_DIR)
        
        # Locate bin folder in extracted content
        # The zip usually contains a root folder like 'ffmpeg-6.0-essentials_build/bin'
        ffmpeg_exe = None
        ffprobe_exe = None
        
        for root, dirs, files in os.walk(EXTRACT_DIR):
            if 'ffmpeg.exe' in files:
                ffmpeg_exe = os.path.join(root, 'ffmpeg.exe')
            if 'ffprobe.exe' in files:
                ffprobe_exe = os.path.join(root, 'ffprobe.exe')
        
        if not ffmpeg_exe or not ffprobe_exe:
            print("Error: Could not find ffmpeg.exe or ffprobe.exe in the downloaded archive.")
            return False

        # Create local bin directory
        if not os.path.exists(BIN_DIR):
            os.makedirs(BIN_DIR)

        # Move files
        shutil.move(ffmpeg_exe, os.path.join(BIN_DIR, 'ffmpeg.exe'))
        shutil.move(ffprobe_exe, os.path.join(BIN_DIR, 'ffprobe.exe'))
        
        print(f"FFmpeg installed successfully to {os.path.abspath(BIN_DIR)}")
        
        # Cleanup
        print("Cleaning up temporary files...")
        os.remove(ZIP_NAME)
        shutil.rmtree(EXTRACT_DIR)
        
        return True

    except Exception as e:
        print(f"An error occurred: {e}")
        return False

if __name__ == "__main__":
    if install_ffmpeg():
        print("Installation successful.")
    else:
        print("Installation failed.")
        sys.exit(1)
