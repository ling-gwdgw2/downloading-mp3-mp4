import os
import sys
import logging
import time
import webview
from pywebview_api import PyWebViewAPI

# Determine base path and app path
if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
    template_folder = os.path.join(base_path, 'templates')
    static_folder = os.path.join(base_path, 'static')
    app_path = os.path.dirname(sys.executable)
else:
    base_path = os.path.dirname(os.path.abspath(__file__))
    template_folder = os.path.join(base_path, 'templates')
    static_folder = os.path.join(base_path, 'static')
    app_path = base_path

# Setup logging
log_file_path = os.path.join(app_path, 'app.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file_path, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logging.info("Phoebe Downloader starting up (Native pywebview mode)...")
logging.info(f"App path: {app_path}")

# Dynamic Engine Loading with Safe Fallback (bypassing PyInstaller's FrozenImporter)
update_path = os.path.join(app_path, 'bin', 'yt-dlp-update')
loaded_dynamic = False
if os.path.exists(update_path):
    frozen_importers = []
    for importer in list(sys.meta_path):
        if "FrozenImporter" in type(importer).__name__:
            frozen_importers.append(importer)
            sys.meta_path.remove(importer)
            
    sys.path.insert(0, update_path)
    try:
        import yt_dlp
        import importlib
        importlib.reload(yt_dlp)
        loaded_dynamic = True
        logging.info(f"Dynamically loaded updated yt-dlp engine from: {update_path} (Version: {yt_dlp.version.__version__})")
    except Exception as e:
        logging.error(f"Failed to import dynamically updated yt-dlp: {e}. Cleaning and falling back to built-in...")
        if update_path in sys.path:
            sys.path.remove(update_path)
        try:
            import shutil
            shutil.rmtree(update_path, ignore_errors=True)
        except Exception:
            pass
    finally:
        for importer in reversed(frozen_importers):
            sys.meta_path.insert(0, importer)

if not loaded_dynamic:
    import yt_dlp
    logging.info(f"Loaded built-in yt-dlp engine (Version: {yt_dlp.version.__version__})")

# FFmpeg setup
BIN_FOLDER = os.path.join(app_path, 'bin')
if os.path.exists(os.path.join(BIN_FOLDER, 'ffmpeg.exe')):
    os.environ["PATH"] += os.pathsep + BIN_FOLDER
    logging.info(f"Added local FFmpeg from {BIN_FOLDER}")

def cleanup_temp_files(api_instance):
    try:
        save_dir = api_instance.config.get('save_folder')
        if save_dir and os.path.exists(save_dir):
            cleaned_count = 0
            for filename in os.listdir(save_dir):
                if filename.endswith('.part') or filename.endswith('.ytdl') or filename.endswith('.temp'):
                    file_path = os.path.join(save_dir, filename)
                    try:
                        os.remove(file_path)
                        cleaned_count += 1
                    except Exception:
                        pass
            if cleaned_count > 0:
                logging.info(f"Startup Cleanup: Removed {cleaned_count} stale temp/part files.")
    except Exception as e:
        logging.error(f"Error during startup cleanup: {e}", exc_info=True)

def disable_close_button():
    try:
        import ctypes
        time.sleep(1)
        hwnd = ctypes.windll.user32.FindWindowW(None, "Phoebe Downloader")
        if hwnd:
            hmenu = ctypes.windll.user32.GetSystemMenu(hwnd, False)
            if hmenu:
                ctypes.windll.user32.DeleteMenu(hmenu, 0xF060, 0x0)
                ctypes.windll.user32.DrawMenuBar(hwnd)
                logging.info("Successfully disabled native Windows close button.")
    except Exception as e:
        logging.warning(f"Failed to disable close button: {e}")

if __name__ == '__main__':
    api = PyWebViewAPI(app_path)
    cleanup_temp_files(api)

    index_html_path = os.path.join(template_folder, 'index.html')

    logging.info(f"Opening PyWebView native GUI window with template: {index_html_path}")
    window = webview.create_window(
        'Phoebe Downloader',
        index_html_path,
        js_api=api,
        width=1280,
        height=820,
        min_size=(1024, 768)
    )
    api.set_window(window)

    # Prevent closing via standard window X button or Alt+F4
    window.events.closing += lambda: False

    # Start webview GUI loop
    webview.start(disable_close_button)
