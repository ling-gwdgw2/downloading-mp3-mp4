import PyInstaller.__main__
import os
import shutil

# Clean previous build
if os.path.exists('dist'):
    shutil.rmtree('dist')
if os.path.exists('build'):
    shutil.rmtree('build')

print("Building executable...")

PyInstaller.__main__.run([
    'app.py',
    '--name=YouTubeDownloader',
    '--onefile',
    '--add-data=templates;templates',
    '--add-data=static;static',
    '--icon=logo.ico',
    '--collect-all=curl_cffi',
    '--noconsole',
    '--clean',
])



print("Build complete.")

# Copy bin folder to dist if it exists
if os.path.exists('bin'):
    print("Copying bin folder (ffmpeg) to dist/...")
    # dist folder might be recreated, so we need to be careful.
    # PyInstaller creates dist/YouTubeDownloader_New.exe
    # We want bin to be in dist/
    if not os.path.exists('dist/bin'):
        shutil.copytree('bin', 'dist/bin')
        print("Bin folder copied.")
    else:
        print("Bin folder already exists in dist.")
else:
    print("Warning: bin folder not found. FFmpeg will not be included.")

print("Executable created in dist/YouTubeDownloader.exe")
