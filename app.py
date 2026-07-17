import os
import re
import sys
import logging
import uuid
import shutil
import zipfile
import urllib.request
import tempfile
import json
import winreg
# pyrefly: ignore [missing-import]
from flask import Flask, render_template, request, jsonify, Response, make_response

# Determine base path and app path
if getattr(sys, 'frozen', False):
    # Running as compiled .exe
    base_path = sys._MEIPASS
    template_folder = os.path.join(base_path, 'templates')
    static_folder = os.path.join(base_path, 'static')
    app_path = os.path.dirname(sys.executable)
else:
    # Running as python script
    base_path = os.path.dirname(os.path.abspath(__file__))
    template_folder = 'templates'
    static_folder = 'static'
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
logging.info("Application starting up...")
logging.info(f"App path: {app_path}")

# Dynamic Engine Loading with Safe Fallback
update_path = os.path.join(app_path, 'bin', 'yt-dlp-update')
loaded_dynamic = False
if os.path.exists(update_path):
    sys.path.insert(0, update_path)
    try:
        import yt_dlp
        loaded_dynamic = True
        logging.info(f"Dynamically loaded updated yt-dlp engine from: {update_path} (Version: {yt_dlp.version.__version__})")
    except Exception as e:
        logging.error(f"Failed to import dynamically updated yt-dlp: {e}. Cleaning and falling back to built-in...")
        if update_path in sys.path:
            sys.path.remove(update_path)
        try:
            shutil.rmtree(update_path, ignore_errors=True)
        except Exception:
            pass

if not loaded_dynamic:
    import yt_dlp
    logging.info(f"Loaded built-in yt-dlp engine (Version: {yt_dlp.version.__version__})")
# pyrefly: ignore [missing-import]
from curl_cffi import requests as curl_requests

app = Flask(__name__)
app.template_folder = template_folder
app.static_folder = static_folder

# Detect Default Windows Downloads Path
def get_windows_downloads_path():
    try:
        sub_key = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub_key) as key:
            path = winreg.QueryValueEx(key, '{374DE290-123F-4565-9164-39C4925E467B}')[0]
            return os.path.normpath(path)
    except Exception:
        return os.path.normpath(os.path.join(os.path.expanduser('~'), 'Downloads'))

def _detect_browsers():
    """Shared browser detection for cookie fallback. Returns list of browser names + None sentinel."""
    detected = []
    local_appdata = os.environ.get('LOCALAPPDATA', '')
    appdata = os.environ.get('APPDATA', '')
    browsers_to_check = [
        ('chrome', os.path.join(local_appdata, 'Google', 'Chrome', 'User Data')),
        ('edge', os.path.join(local_appdata, 'Microsoft', 'Edge', 'User Data')),
        ('firefox', os.path.join(appdata, 'Mozilla', 'Firefox', 'Profiles')),
        ('opera', os.path.join(appdata, 'Opera Software', 'Opera Stable')),
    ]
    for name, path in browsers_to_check:
        if path and os.path.exists(path):
            detected.append(name)
    detected.append(None)  # Sentinel: try without cookies last
    return detected

def _is_youtube_url(target_url):
    """Check if URL requires YouTube cookie fallback."""
    return 'youtube.com' in target_url or 'youtu.be' in target_url or target_url.startswith('ytsearch')

def extract_info_with_fallback(target_url, ydl_opts):
    if not _is_youtube_url(target_url):
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(target_url, download=False)

    last_err = None
    for browser in _detect_browsers():
        opts = ydl_opts.copy()
        if browser:
            opts['cookiesfrombrowser'] = (browser,)
        else:
            opts.pop('cookiesfrombrowser', None)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(target_url, download=False)
        except Exception as e:
            if browser is not None:
                logging.info(f"Could not load cookies from '{browser}' ({e}). Trying next fallback...")
                last_err = e
                continue
            else:
                raise e
    raise last_err

def download_url_with_fallback(ydl_opts, target_url):
    if not _is_youtube_url(target_url):
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([target_url])
            return

    last_err = None
    for browser in _detect_browsers():
        opts = ydl_opts.copy()
        if browser:
            opts['cookiesfrombrowser'] = (browser,)
        else:
            opts.pop('cookiesfrombrowser', None)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([target_url])
                return
        except Exception as e:
            if browser is not None:
                logging.info(f"Could not load cookies from '{browser}' ({e}). Trying next fallback...")
                last_err = e
                continue
            else:
                raise e
    raise last_err

# Settings Store
config = {
    'save_folder': get_windows_downloads_path()
}

# Global dictionary to track active download states
import threading as _threading
_progress_lock = _threading.Lock()
download_progress = {}

cancelled_downloads = set()

import time
last_ping_time = time.time()

def auto_shutdown_monitor():
    global last_ping_time
    import time
    time.sleep(20)
    while True:
        start_loop = time.time()
        time.sleep(5)
        elapsed = time.time() - start_loop
        
        # Detect system suspend/sleep or CPU freeze and reset clock
        if elapsed > 15:
            logging.info(f"Auto-Shutdown: System sleep or cpu lag detected (elapsed {elapsed:.1f}s). Resetting heartbeat clock.")
            last_ping_time = time.time()
            continue
            
        # 90 seconds threshold to prevent background tab throttling false positives
        if time.time() - last_ping_time > 90:
            # Prevent shutdown if there are active downloads
            has_active_downloads = False
            with _progress_lock:
                for d_id in list(download_progress.keys()):
                    if download_progress[d_id].get('status') in ['starting', 'downloading', 'processing']:
                        has_active_downloads = True
                        break
            
            if has_active_downloads:
                last_ping_time = time.time()
                continue
                
            logging.info("Auto-Shutdown: No browser heartbeat ping detected for 90 seconds. Shutting down server gracefully...")
            with _progress_lock:
                for d_id in list(download_progress.keys()):
                    if download_progress[d_id].get('status') in ['starting', 'downloading', 'processing']:
                        cancelled_downloads.add(d_id)
            time.sleep(1.5)
            try:
                cleanup_temp_files()
            except Exception:
                pass
            os._exit(0)

_threading.Thread(target=auto_shutdown_monitor, daemon=True).start()

auto_update_status = {
    'status': 'idle',
    'message': ''
}

def auto_update_engine_on_startup():
    global auto_update_status
    logging.info("Auto-Update: Checking for yt-dlp engine updates on startup...")
    auto_update_status['status'] = 'checking'
    auto_update_status['message'] = 'Checking for engine updates...'
    try:
        import json
        import urllib.request
        import zipfile
        import tempfile
        import shutil
        
        current_version = yt_dlp.version.__version__
        
        # 1. Fetch PyPI data
        req = urllib.request.Request("https://pypi.org/pypi/yt-dlp/json", headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as res:
            pypi_data = json.loads(res.read().decode('utf-8'))
            latest_version = pypi_data['info']['version']
            
        if current_version != latest_version:
            logging.info(f"Auto-Update: Update available (v{latest_version}). Preparing download...")
            auto_update_status['status'] = 'downloading'
            auto_update_status['message'] = f'Downloading engine update v{latest_version}...'
            
            # Find whl download url
            urls = pypi_data['urls']
            whl_url = None
            for url_info in urls:
                if url_info['filename'].endswith('.whl'):
                    whl_url = url_info['url']
                    break
                    
            if not whl_url:
                raise Exception("No valid wheel package found on PyPI.")
                
            temp_dir = tempfile.gettempdir()
            temp_file_path = os.path.join(temp_dir, "yt_dlp_auto_update.whl")
            
            # Download
            req_dl = urllib.request.Request(whl_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req_dl, timeout=60) as response_dl:
                with open(temp_file_path, 'wb') as out_file:
                    out_file.write(response_dl.read())
                    
            # Extract
            target_dir = os.path.join(app_path, 'bin', 'yt-dlp-update')
            if not os.path.exists(target_dir):
                os.makedirs(target_dir)
                
            with zipfile.ZipFile(temp_file_path, 'r') as zip_ref:
                for file in zip_ref.namelist():
                    if file.startswith('yt_dlp/'):
                        zip_ref.extract(file, target_dir)
                        
            # Cleanup temp file
            try:
                os.remove(temp_file_path)
            except Exception:
                pass
                
            logging.info(f"Auto-Update: Engine successfully updated in background to v{latest_version}. Ready for restart.")
            auto_update_status['status'] = 'completed'
            auto_update_status['message'] = f'Engine updated to v{latest_version}. Restart app to apply.'
        else:
            logging.info("Auto-Update: Engine is already the latest version.")
            auto_update_status['status'] = 'up_to_date'
            auto_update_status['message'] = 'Engine is up-to-date.'
            
    except Exception as e:
        logging.error(f"Auto-Update failed: {e}")
        auto_update_status['status'] = 'error'
        auto_update_status['message'] = f'Check/Update failed: {str(e)}'

_threading.Thread(target=auto_update_engine_on_startup, daemon=True).start()

def _schedule_cleanup(download_id, delay=10):
    """Remove stale download entries after delay seconds to prevent memory leak."""
    import time
    def _cleanup():
        time.sleep(delay)
        with _progress_lock:
            download_progress.pop(download_id, None)
        cancelled_downloads.discard(download_id)
    _threading.Thread(target=_cleanup, daemon=True).start()

def format_bytes(b):
    if b is None or b == 0:
        return '0 B'
    for unit in ['B', 'KB', 'MB', 'GB']:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"

# FFmpeg setup
BIN_FOLDER = os.path.join(app_path, 'bin')
if os.path.exists(os.path.join(BIN_FOLDER, 'ffmpeg.exe')):
    os.environ["PATH"] += os.pathsep + BIN_FOLDER
    logging.info(f"Added local FFmpeg from {BIN_FOLDER}")

# Middleware to check FFmpeg requirements
@app.before_request
def check_ffmpeg():
    if request.path.startswith('/setup') or request.path.startswith('/static') or request.path == '/shutdown' or request.path == '/api/logs' or request.path == '/update_engine' or request.path == '/engine_status' or request.path == '/revert_engine':
        return
        
    ffmpeg_path = os.path.join(BIN_FOLDER, 'ffmpeg.exe')
    if not os.path.exists(ffmpeg_path):
        # pyrefly: ignore [missing-import]
        from flask import redirect, url_for
        return redirect(url_for('setup_page'))

@app.route('/')
def index():
    resp = make_response(render_template('index.html'))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

@app.route('/setup')
def setup_page():
    resp = make_response(render_template('setup.html'))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

@app.route('/settings', methods=['GET'])
def get_settings():
    return jsonify(config)

def ask_directory_thread(result_list):
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw() # Hide root Tk window
        root.attributes('-topmost', True) # Focus on top of all windows
        folder = filedialog.askdirectory(parent=root, title="Select Save Folder")
        root.destroy()
        result_list.append(folder)
    except Exception as e:
        logging.error(f"Tkinter dialog error: {e}", exc_info=True)

@app.route('/select_folder', methods=['POST'])
def select_folder():
    # Allow manual path input as fallback
    manual_path = request.form.get('manual_path')
    if manual_path:
        manual_path = os.path.normpath(manual_path)
        if os.path.isdir(manual_path):
            config['save_folder'] = manual_path
            return jsonify({'save_folder': manual_path})
        else:
            return jsonify({'error': 'Invalid directory path. Please check if the folder exists.'}), 400

    import threading
    res = []
    t = threading.Thread(target=ask_directory_thread, args=(res,))
    t.start()
    t.join(timeout=60.0) # Prevent permanent hang by setting a timeout
    
    if res and res[0]:
        selected_path = os.path.normpath(res[0])
        config['save_folder'] = selected_path
        return jsonify({'save_folder': selected_path})
    
    return jsonify({
        'save_folder': config['save_folder'],
        'dialog_failed': len(res) == 0
    })

@app.route('/open_folder', methods=['POST'])
def open_folder():
    try:
        folder_path = config.get('save_folder')
        if os.path.exists(folder_path):
            os.startfile(folder_path)
            return jsonify({'status': 'opened'})
        else:
            return jsonify({'error': 'Folder path does not exist.'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/setup/download')
def setup_download():
    def generate():
        FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
        ZIP_NAME = os.path.join(app_path, "ffmpeg.zip")
        EXTRACT_DIR = os.path.join(app_path, "ffmpeg_temp")
        BIN_DIR = BIN_FOLDER
        
        yield "data: {\"status\": \"starting\", \"percent\": 0}\n\n"
        
        try:
            req = urllib.request.Request(FFMPEG_URL, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                total_size = int(response.info().get('Content-Length', 0))
                downloaded = 0
                block_size = 1024 * 64
                
                with open(ZIP_NAME, 'wb') as f:
                    while True:
                        buffer = response.read(block_size)
                        if not buffer:
                            break
                        downloaded += len(buffer)
                        f.write(buffer)
                        percent = int(downloaded * 100 / total_size) if total_size > 0 else 0
                        yield f"data: {{\"status\": \"downloading\", \"percent\": {percent}}}\n\n"
            
            yield "data: {\"status\": \"extracting\", \"percent\": 90}\n\n"
            
            with zipfile.ZipFile(ZIP_NAME, 'r') as zip_ref:
                zip_ref.extractall(EXTRACT_DIR)
                
            ffmpeg_exe = None
            ffprobe_exe = None
            for root, dirs, files in os.walk(EXTRACT_DIR):
                if 'ffmpeg.exe' in files:
                    ffmpeg_exe = os.path.join(root, 'ffmpeg.exe')
                if 'ffprobe.exe' in files:
                    ffprobe_exe = os.path.join(root, 'ffprobe.exe')
                    
            if ffmpeg_exe and ffprobe_exe:
                if not os.path.exists(BIN_DIR):
                    os.makedirs(BIN_DIR)
                shutil.move(ffmpeg_exe, os.path.join(BIN_DIR, 'ffmpeg.exe'))
                shutil.move(ffprobe_exe, os.path.join(BIN_DIR, 'ffprobe.exe'))
                
            # Cleanup
            if os.path.exists(ZIP_NAME):
                os.remove(ZIP_NAME)
            if os.path.exists(EXTRACT_DIR):
                shutil.rmtree(EXTRACT_DIR)
                
            # Add to PATH
            os.environ["PATH"] += os.pathsep + BIN_DIR
            
            yield "data: {\"status\": \"success\", \"percent\": 100}\n\n"
        except Exception as e:
            if os.path.exists(ZIP_NAME): os.remove(ZIP_NAME)
            if os.path.exists(EXTRACT_DIR): shutil.rmtree(EXTRACT_DIR)
            yield f"data: {{\"status\": \"error\", \"message\": \"{str(e)}\"}}\n\n"
            
    return Response(generate(), mimetype='text/event-stream')

def extract_missav(url):
    try:
        response = curl_requests.get(url, impersonate="chrome120", timeout=15)
        html = response.text
        
        # Extract title
        title_match = re.search(r'<meta property="og:title" content="([^"]+)"', html)
        if not title_match:
            title_match = re.search(r'<meta property="og:title"\s+content="([^"]+)"', html)
        title = title_match.group(1) if title_match else "MissAV Video"
        title = title.replace(" - MissAV", "").replace(" - missav", "").strip()

        # Extract packed m3u8
        match = re.search(r"eval\(function\(p,a,c,k,e,d\).*?return p}\('(.*?)',\s*(\d+),\s*(\d+),\s*'(.*?)'\.split\('\|'\)", html, re.DOTALL)
        if not match:
            return None, None

        p, a, c, k = match.groups()
        a = int(a)
        c = int(c)
        k = k.split('|')

        def baseN(num, b):
            if num == 0: return "0"
            chars = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
            res = ""
            while num > 0:
                res = chars[num % b] + res
                num //= b
            return res

        unpacked = p
        for i in range(c - 1, -1, -1):
            if k[i]:
                word = baseN(i, a)
                unpacked = re.sub(r'\b' + re.escape(word) + r'\b', k[i], unpacked)

        m_match = re.search(r"(https?://[^\s\"']+\.m3u8)", unpacked)
        if m_match:
            return m_match.group(1), title
        
        return None, None
    except Exception as e:
        logging.error(f"MissAV extraction error: {e}", exc_info=True)
        return None, None

def parse_spotify_playlist(url):
    import base64
    if 'nd=1' not in url:
        if '?' in url:
            url += '&nd=1'
        else:
            url += '?nd=1'
            
    playlist_id_match = re.search(r'/playlist/([a-zA-Z0-9]+)', url)
    if not playlist_id_match:
        raise Exception("Invalid Spotify playlist URL")
    playlist_id = playlist_id_match.group(1)
    
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    
    with urllib.request.urlopen(req, timeout=15) as response:
        html = response.read().decode('utf-8')
        
    script_match = re.search(r'<script[^>]*id="initialState"[^>]*>([\s\S]*?)</script>', html)
    if not script_match:
        raise Exception("Failed to extract Spotify metadata - initialState not found")
        
    encoded_data = script_match.group(1).strip()
    decoded_bytes = base64.b64decode(encoded_data)
    data = json.loads(decoded_bytes.decode('utf-8'))
    
    playlist_key = f"spotify:playlist:{playlist_id}"
    items_dict = data.get("entities", {}).get("items", {})
    if playlist_key not in items_dict:
        raise Exception("Playlist not found in Spotify metadata")
        
    playlist_data = items_dict[playlist_key]
    playlist_name = playlist_data.get("name", "Spotify Playlist")
    
    images_items = playlist_data.get("images", {}).get("items", [])
    playlist_thumbnail = ""
    if images_items:
        sources = images_items[0].get("sources", [])
        if sources:
            playlist_thumbnail = max(sources, key=lambda x: x.get("width", 0)).get("url", "")
            
    content = playlist_data.get("content", {})
    items = content.get("items", [])
    
    playlist_videos = []
    for idx, item in enumerate(items):
        item_v2 = item.get("itemV2", {})
        if not item_v2:
            continue
        track_data = item_v2.get("data", {})
        if not track_data or track_data.get("__typename") != "Track":
            continue
            
        track_name = track_data.get("name", "Unknown Track")
        
        artists_items = track_data.get("artists", {}).get("items", [])
        artist_names = ", ".join([a.get("profile", {}).get("name", "") for a in artists_items if a.get("profile")])
        if not artist_names:
            artist_names = "Unknown Artist"
            
        album_name = track_data.get("albumOfTrack", {}).get("name", "Unknown Album")
        
        cover_sources = track_data.get("albumOfTrack", {}).get("coverArt", {}).get("sources", [])
        cover_url = ""
        if cover_sources:
            cover_url = max(cover_sources, key=lambda x: x.get("width", 0)).get("url", "")
            
        duration_dict = track_data.get("duration", {})
        duration_ms = 0
        if isinstance(duration_dict, dict):
            duration_ms = duration_dict.get("totalMilliseconds") or duration_dict.get("milliseconds") or 0
        elif isinstance(duration_dict, (int, float)):
            duration_ms = int(duration_dict)
        duration_secs = duration_ms // 1000
        
        payload = {
            'title': track_name,
            'artist': artist_names,
            'cover': cover_url
        }
        payload_str = json.dumps(payload)
        encoded_payload = base64.b64encode(payload_str.encode('utf-8')).decode('utf-8')
        virtual_url = f"spotify_track:{encoded_payload}"
        
        playlist_videos.append({
            'index': idx,
            'id': f"spotify_{idx}",
            'title': f"{track_name} - {artist_names}",
            'uploader': artist_names,
            'duration': duration_secs,
            'thumbnail': cover_url,
            'url': virtual_url
        })
        
    return {
        'title': f"Spotify Playlist: {playlist_name}",
        'thumbnail': playlist_thumbnail,
        'duration': f"{len(playlist_videos)} items",
        'uploader': "Spotify",
        'resolutions': ['mp3', 'm4a', 'flac', 'wav'],
        'url': url,
        'is_playlist': True,
        'playlist_videos': playlist_videos
    }

def parse_spotify_track(url):
    import base64
    if 'nd=1' not in url:
        if '?' in url:
            url += '&nd=1'
        else:
            url += '?nd=1'
            
    track_id_match = re.search(r'/track/([a-zA-Z0-9]+)', url)
    if not track_id_match:
        raise Exception("Invalid Spotify track URL")
    track_id = track_id_match.group(1)
    
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    
    with urllib.request.urlopen(req, timeout=15) as response:
        html = response.read().decode('utf-8')
        
    script_match = re.search(r'<script[^>]*id="initialState"[^>]*>([\s\S]*?)</script>', html)
    if not script_match:
        raise Exception("Failed to extract Spotify metadata - initialState not found")
        
    encoded_data = script_match.group(1).strip()
    decoded_bytes = base64.b64decode(encoded_data)
    data = json.loads(decoded_bytes.decode('utf-8'))
    
    track_key = f"spotify:track:{track_id}"
    items_dict = data.get("entities", {}).get("items", {})
    if track_key not in items_dict:
        raise Exception("Track not found in Spotify metadata")
        
    track_data = items_dict[track_key]
    track_name = track_data.get("name", "Unknown Track")
    
    artists_items = track_data.get("artists", {}).get("items", [])
    artist_names = ", ".join([a.get("profile", {}).get("name", "") for a in artists_items if a.get("profile")])
    if not artist_names:
        artist_names = "Unknown Artist"
        
    album_name = track_data.get("albumOfTrack", {}).get("name", "Unknown Album")
    
    cover_sources = track_data.get("albumOfTrack", {}).get("coverArt", {}).get("sources", [])
    cover_url = ""
    if cover_sources:
        cover_url = max(cover_sources, key=lambda x: x.get("width", 0)).get("url", "")
        
    duration_dict = track_data.get("duration", {})
    duration_ms = 0
    if isinstance(duration_dict, dict):
        duration_ms = duration_dict.get("totalMilliseconds") or duration_dict.get("milliseconds") or 0
    elif isinstance(duration_dict, (int, float)):
        duration_ms = int(duration_dict)
    duration_secs = duration_ms // 1000
    
    payload = {
        'title': track_name,
        'artist': artist_names,
        'cover': cover_url
    }
    payload_str = json.dumps(payload)
    encoded_payload = base64.b64encode(payload_str.encode('utf-8')).decode('utf-8')
    virtual_url = f"spotify_track:{encoded_payload}"
    
    return {
        'title': f"{track_name} - {artist_names}",
        'thumbnail': cover_url,
        'duration': f"{duration_secs // 60}:{duration_secs % 60:02d}" if duration_secs > 0 else "",
        'uploader': artist_names,
        'resolutions': ['mp3', 'm4a', 'flac', 'wav'],
        'url': virtual_url
    }

@app.route('/info', methods=['POST'])
def get_info():
    url = request.form.get('url')
    if not url:
        return jsonify({'error': 'Please provide a URL'}), 400

    try:
        urls = [u.strip() for u in url.replace('\n', ',').split(',') if u.strip()]
        
        if len(urls) > 1:
            return jsonify({
                'title': f'Batch Download ({len(urls)} links)',
                'thumbnail': 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=500',
                'duration': 'N/A',
                'uploader': 'Batch Mode',
                'resolutions': ['720p', '1080p', 'mp3'],
                'url': url
            })

        target_url = urls[0]
        if 'spotify.com/playlist/' in target_url:
            spotify_info = parse_spotify_playlist(target_url)
            return jsonify(spotify_info)
        elif 'spotify.com/track/' in target_url:
            spotify_info = parse_spotify_track(target_url)
            return jsonify(spotify_info)

        # Check if keyword search query
        if not target_url.startswith('http://') and not target_url.startswith('https://'):
            target_url = f"ytsearch1:{target_url}"

        is_missav = 'missav.' in target_url
        custom_title = None

        if is_missav:
            m3u8_url, custom_title = extract_missav(target_url)
            if not m3u8_url:
                return jsonify({'error': 'Failed to extract video from MissAV.'}), 400
            target_url = m3u8_url

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'nocache': True,
        }
        if 'list=' in target_url or '/playlist' in target_url:
            ydl_opts['extract_flat'] = True
        if is_missav:
            from urllib.parse import urlparse
            ydl_opts['referer'] = f"https://{urlparse(target_url).netloc}/"

        info = extract_info_with_fallback(target_url, ydl_opts)
            
        # Check if playlist or search results
        if info.get('_type') == 'playlist':
            entries = list(info.get('entries', []))
            if target_url.startswith('ytsearch1:') and entries and entries[0]:
                # Search results, extract first entry and treat as single video
                info = entries[0]
                url = info.get('webpage_url') or f"https://www.youtube.com/watch?v={info.get('id')}"
            else:
                playlist_videos = []
                for idx, entry in enumerate(entries):
                    if entry:
                        playlist_videos.append({
                            'index': idx,
                            'id': entry.get('id'),
                            'title': entry.get('title') or f"Video #{idx+1}",
                            'uploader': entry.get('uploader') or 'Unknown',
                            'duration': entry.get('duration'),
                            'thumbnail': entry.get('thumbnail') or '',
                            'url': entry.get('webpage_url') or f"https://www.youtube.com/watch?v={entry.get('id')}"
                        })
                return jsonify({
                    'title': f"Playlist: {info.get('title', 'Playlist')}",
                    'thumbnail': entries[0].get('thumbnail') if entries and entries[0] else '',
                    'duration': f"{len(entries)} items",
                    'uploader': info.get('uploader', 'Unknown'),
                    'resolutions': ['2160p (4K)', '1080p (Full HD)', '720p (HD)', '480p', 'mp3'],
                    'url': target_url,
                    'is_playlist': True,
                    'playlist_videos': playlist_videos
                })

        # Extract available resolutions
        formats = info.get('formats', [])
        resolutions = set()
        for f in formats:
            if f.get('vcodec') != 'none' and f.get('height'):
                resolutions.add(f.get('height'))
        
        # Sort resolutions in descending order
        sorted_heights = sorted(list(resolutions), reverse=True)
        
        available_qualities = []
        for h in sorted_heights:
            if h == 2160:
                available_qualities.append('2160p (4K)')
            elif h == 1440:
                available_qualities.append('1440p (2K)')
            elif h == 1080:
                available_qualities.append('1080p (Full HD)')
            elif h == 720:
                available_qualities.append('720p (HD)')
            elif h >= 360:
                available_qualities.append(f'{h}p')
        
        # Ensure we always have at least some video options or default fallbacks if none detected
        if not any(q.endswith('p') or '(' in q for q in available_qualities):
            available_qualities.extend(['1080p (Full HD)', '720p (HD)', '480p'])
            
        available_qualities.append('mp3')

        # Extract audio stream details
        best_audio_codec = None
        max_audio_bitrate = 0
        best_audio_ext = None
        
        for f in formats:
            codec = f.get('acodec')
            if codec and codec != 'none':
                bitrate = f.get('abr') or f.get('tbr') or 0
                if bitrate > max_audio_bitrate:
                    max_audio_bitrate = int(bitrate)
                    best_audio_codec = codec.split('.')[0]
                    best_audio_ext = f.get('ext')
                    
        # Fallback if no audio codec details found
        if not best_audio_codec:
            best_audio_codec = "aac"
            max_audio_bitrate = 128
            best_audio_ext = "m4a"
            
        # Formulate smart download recommendations
        recommendation = ""
        codec_lower = best_audio_codec.lower()
        if 'opus' in codec_lower:
            recommendation = " เสียงต้นฉบับบน YouTube เป็น Opus คุณภาพสูง แนะนำให้เลือก M4A Original เพื่อดาวน์โหลดเร็วและไม่เสียคุณภาพ หรือเลือก MP3 320kbps / Lossless FLAC เพื่อแปลงเป็นฟอร์แมตยอดนิยม"
        elif 'mp4a' in codec_lower or 'aac' in codec_lower:
            if max_audio_bitrate >= 192:
                recommendation = f" เสียงต้นฉบับเป็น AAC คุณภาพสูง ({max_audio_bitrate} kbps) แนะนำให้เลือก M4A Original หรือ MP3 320kbps เพื่อคงคุณภาพความละเอียดดนตรีไว้ครบถ้วน"
            else:
                recommendation = f" เสียงต้นฉบับเป็น AAC ความละเอียดปกติ ({max_audio_bitrate} kbps) แนะนำให้เลือก M4A Original เพื่อบันทึกเสียงสดต้นฉบับได้ทันทีโดยไม่ต้องแปลงสัญญาณใหม่ หรือเลือก MP3 192kbps"
        elif 'mp3' in codec_lower:
            recommendation = f" เสียงต้นฉบับเป็น MP3 ({max_audio_bitrate} kbps) แนะนำให้ดาวน์โหลดเป็น MP3 320kbps หรือ M4A Original เพื่อให้ได้เสียงที่คมชัดที่สุดตามคุณภาพดั้งเดิม"
        else:
            recommendation = f" เสียงต้นฉบับเป็นฟอร์แมต {best_audio_codec.upper()} แนะนำให้ดาวน์โหลดเป็น M4A Original หรือ MP3 320kbps เพื่อการประมวลผลและการใช้งานที่เสถียรที่สุด"

        return jsonify({
            'title': custom_title if custom_title else info.get('title'),
            'thumbnail': info.get('thumbnail'),
            'duration': info.get('duration_string', ''),
            'uploader': info.get('uploader', 'Unknown'),
            'resolutions': available_qualities,
            'url': url,
            'audio_codec': best_audio_codec,
            'audio_bitrate': max_audio_bitrate if max_audio_bitrate > 0 else None,
            'audio_recommendation': recommendation
        })
    except Exception as e:
        logging.error(f"Error in get_info for URL {url}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/prepare_download', methods=['POST'])
def prepare_download():
    url = request.form.get('url')
    format_type = request.form.get('format_type')
    bitrate = request.form.get('bitrate', '192')
    subtitles = request.form.get('subtitles', 'false')
    download_id = str(uuid.uuid4())
    return render_template('downloading.html', url=url, format_type=format_type, bitrate=bitrate, subtitles=subtitles, download_id=download_id, save_folder=config['save_folder'])

@app.route('/download_start', methods=['POST'])
def download_start():
    url = request.form.get('url')
    format_type = request.form.get('format_type')
    bitrate = request.form.get('bitrate', '192')
    subtitles = request.form.get('subtitles', 'false')
    download_id = request.form.get('download_id')
    video_container = request.form.get('video_container', 'mp4')
    embed_metadata = request.form.get('embed_metadata', 'false')

    if not url or not download_id:
        return jsonify({'error': 'Missing parameters'}), 400

    download_progress[download_id] = {
        'status': 'starting',
        'percent': 0,
        'speed': '0 KB/s',
        'eta': 'Unknown'
    }

    import threading
    threading.Thread(
        target=run_download_thread,
        args=(download_id, url, format_type, bitrate, subtitles, video_container, embed_metadata),
        daemon=True
    ).start()

    return jsonify({'status': 'started'})

def embed_metadata_to_file(file_path, title, artist, thumbnail_url):
    try:
        if not os.path.exists(file_path):
            return
            
        cover_bytes = None
        if thumbnail_url:
            try:
                req = urllib.request.Request(thumbnail_url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                })
                with urllib.request.urlopen(req, timeout=10) as response:
                    cover_bytes = response.read()
            except Exception as e:
                logging.warning(f"Failed to download cover art from {thumbnail_url}: {e}")

        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.mp3':
            from mutagen.id3 import ID3, APIC, TIT2, TPE1
            try:
                try:
                    tags = ID3(file_path)
                except Exception:
                    tags = ID3()
                if title:
                    tags.add(TIT2(encoding=3, text=title))
                if artist:
                    tags.add(TPE1(encoding=3, text=artist))
                if cover_bytes:
                    tags.add(APIC(
                        encoding=3,
                        mime='image/jpeg',
                        type=3,
                        desc=u'Cover',
                        data=cover_bytes
                    ))
                tags.save(file_path, v2_version=3)
                logging.info(f"Successfully tagged MP3 file: {file_path}")
            except Exception as mp3_err:
                logging.error(f"Error tagging MP3 {file_path}: {mp3_err}")
        elif ext == '.flac':
            from mutagen.flac import FLAC, Picture
            try:
                audio = FLAC(file_path)
                if title:
                    audio["title"] = title
                if artist:
                    audio["artist"] = artist
                if cover_bytes:
                    pic = Picture()
                    pic.data = cover_bytes
                    pic.type = 3
                    pic.mime = "image/jpeg"
                    pic.desc = u"Cover"
                    audio.clear_pictures()
                    audio.add_picture(pic)
                audio.save()
                logging.info(f"Successfully tagged FLAC file: {file_path}")
            except Exception as flac_err:
                logging.error(f"Error tagging FLAC {file_path}: {flac_err}")
        elif ext == '.wav':
            from mutagen.wave import WAVE
            from mutagen.id3 import ID3, APIC, TIT2, TPE1
            try:
                audio = WAVE(file_path)
                try:
                    audio.add_tags()
                except Exception:
                    pass
                tags = audio.tags
                if tags is not None:
                    if title:
                        tags.add(TIT2(encoding=3, text=title))
                    if artist:
                        tags.add(TPE1(encoding=3, text=artist))
                    if cover_bytes:
                        tags.add(APIC(
                            encoding=3,
                            mime='image/jpeg',
                            type=3,
                            desc=u'Cover',
                            data=cover_bytes
                        ))
                    audio.save()
                    logging.info(f"Successfully tagged WAV file: {file_path}")
            except Exception as wav_err:
                logging.error(f"Error tagging WAV {file_path}: {wav_err}")
        elif ext in ['.m4a', '.mp4']:
            from mutagen.mp4 import MP4, MP4Cover
            try:
                audio = MP4(file_path)
                if title:
                    audio["\xa9nam"] = title
                if artist:
                    audio["\xa9ART"] = artist
                if cover_bytes and ext == '.m4a':
                    audio["covr"] = [MP4Cover(cover_bytes, imageformat=MP4Cover.FORMAT_JPEG)]
                audio.save()
                logging.info(f"Successfully tagged {ext.upper()} file: {file_path}")
            except Exception as mp4_err:
                logging.error(f"Error tagging {ext.upper()} {file_path}: {mp4_err}")
    except Exception as e:
        logging.error(f"Error in embed_metadata_to_file for {file_path}: {e}", exc_info=True)

def run_download_thread(download_id, url, format_type, bitrate, subtitles, video_container='mp4', embed_metadata='false'):
    try:
        save_dir = config.get('save_folder')
        os.makedirs(save_dir, exist_ok=True)
        
        urls = [u.strip() for u in url.replace('\n', ',').split(',') if u.strip()]
        
        # Check if first URL is a playlist
        is_playlist = False
        if len(urls) == 1:
            if urls[0].startswith("spotify_track:"):
                is_playlist = False
            else:
                ydl_opts_check = {'quiet': True, 'extract_flat': True, 'nocache': True}
                check_info = extract_info_with_fallback(urls[0], ydl_opts_check)
                if check_info.get('_type') == 'playlist':
                    is_playlist = True

        def make_progress_hook(d_id):
            def hook(d):
                if d_id in cancelled_downloads:
                    raise Exception("Download cancelled by user")
                if d['status'] == 'downloading':
                    total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                    downloaded = d.get('downloaded_bytes', 0)
                    percent_val = 0
                    if total > 0:
                        percent_val = int(downloaded * 100 / total)
                    
                    percent_str = d.get('_percent_str', '0%').replace('%', '').strip()
                    try:
                        percent_val = int(float(percent_str))
                    except ValueError:
                        pass
                        
                    speed_str = d.get('_speed_str', 'Unknown speed').strip()
                    eta_str = d.get('_eta_str', 'Unknown ETA').strip()
                    size_str = f"{format_bytes(downloaded)} / {format_bytes(total)}" if total > 0 else format_bytes(downloaded)
                    
                    download_progress[d_id] = {
                        'status': 'downloading',
                        'percent': percent_val,
                        'speed': speed_str,
                        'eta': eta_str,
                        'size': size_str
                    }
                elif d['status'] == 'finished':
                    download_progress[d_id] = {
                        'status': 'processing',
                        'percent': 99,
                        'speed': 'Processing...',
                        'eta': '00:00',
                        'size': 'Merging...'
                    }
            return hook

        _tagged_files = set()  # Prevent duplicate tagging per download session

        def make_postprocessor_hook(d_id, override_title=None, override_artist=None, override_cover=None):
            def hook(d):
                if d_id in cancelled_downloads:
                    raise Exception("Download cancelled by user")
                if d.get('status') == 'finished' and embed_metadata == 'true':
                    filename = d.get('filepath') or d.get('filename')
                    if not filename:
                        info_temp = d.get('info_dict', {})
                        filename = info_temp.get('filepath') or info_temp.get('_filename')
                    
                    if filename and os.path.exists(filename) and filename not in _tagged_files:
                        ext = os.path.splitext(filename)[1].lower()
                        if ext in ['.mp3', '.m4a', '.mp4', '.mkv', '.webm', '.flac', '.wav']:
                            _tagged_files.add(filename)
                            info = d.get('info_dict', {})
                            title = override_title or info.get('title')
                            artist = override_artist or info.get('uploader') or info.get('artist')
                            
                            thumbnail = override_cover or info.get('thumbnail')
                            if not thumbnail and info.get('thumbnails'):
                                thumbnail = info.get('thumbnails')[-1].get('url')
                                
                            embed_metadata_to_file(filename, title, artist, thumbnail)
            return hook

        output_template = os.path.join(save_dir, '%(title)s.%(ext)s')
        ydl_opts = {
            'outtmpl': output_template,
            'quiet': True,
            'nocache': True,
            'progress_hooks': [make_progress_hook(download_id)],
            'postprocessor_hooks': [make_postprocessor_hook(download_id)],
            'retries': 10,
            'fragment_retries': 10
        }
        
        if is_playlist:
            if subtitles == 'true':
                ydl_opts.update({
                    'writesubtitles': True,
                    'writeautomaticsub': True,
                    'embedsubtitles': True,
                    'postprocessors': [{'key': 'FFmpegEmbedSubtitle'}]
                })

            if format_type == 'mp3':
                ydl_opts.update({
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': bitrate,
                    }],
                })
            elif format_type == 'm4a':
                ydl_opts.update({
                    'format': 'bestaudio[ext=m4a]/bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'm4a',
                    }],
                })
            elif format_type == 'flac':
                ydl_opts.update({
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'flac',
                    }],
                })
            elif format_type == 'wav':
                ydl_opts.update({
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'wav',
                    }],
                })
            elif format_type.startswith('mp4_'):
                try:
                    height = int(format_type.split('_')[1])
                except (IndexError, ValueError):
                    height = 720
                ydl_opts.update({
                    'format': f'bestvideo[height<={height}]+bestaudio/best[height<={height}]/best[height<={height}]/best',
                    'merge_output_format': video_container
                })
            else:
                ydl_opts.update({
                    'format': 'best[ext=mp4][height<=720]/best[height<=720]/best',
                    'merge_output_format': video_container
                })
                
            download_url_with_fallback(ydl_opts, urls[0])
        else:
            # Batch URLs
            total_batch = len(urls)
            completed_batch = 0
            failed_batch = 0
            for batch_idx, target_url in enumerate(urls):
                if download_id in cancelled_downloads:
                    raise Exception("Download cancelled by user")
                is_missav = 'missav.' in target_url
                final_url = target_url
                custom_title = None
                
                override_title = None
                override_artist = None
                override_cover = None

                if target_url.startswith("spotify_track:"):
                    import base64
                    try:
                        encoded_payload = target_url.split("spotify_track:")[1]
                        decoded_str = base64.b64decode(encoded_payload).decode('utf-8')
                        payload = json.loads(decoded_str)
                        override_title = payload.get('title')
                        override_artist = payload.get('artist')
                        override_cover = payload.get('cover')
                        final_url = f"ytsearch1:{override_artist} - {override_title}"
                        custom_title = override_title
                    except Exception as e:
                        logging.error(f"Failed to decode Spotify track payload: {e}")
                        failed_batch += 1
                        continue

                if is_missav:
                    m3u8_url, custom_title = extract_missav(target_url)
                    if not m3u8_url:
                        failed_batch += 1
                        continue
                    final_url = m3u8_url

                output_template = os.path.join(save_dir, '%(title)s.%(ext)s')
                if custom_title:
                    safe_title = re.sub(r'[\\/*?:"<>|]', "", custom_title)
                    safe_title = safe_title[:100].strip()
                    output_template = os.path.join(save_dir, f"{safe_title}.%(ext)s")
                
                # Update progress to show batch status
                batch_percent = int((batch_idx / total_batch) * 100)
                download_progress[download_id] = {
                    'status': 'downloading',
                    'percent': max(batch_percent, 1),
                    'speed': f'Track {batch_idx + 1}/{total_batch}',
                    'eta': f'{total_batch - batch_idx} remaining',
                    'size': f'Done: {completed_batch} | Failed: {failed_batch}'
                }

                ydl_opts = {
                    'outtmpl': output_template,
                    'quiet': True,
                    'nocache': True,
                    'progress_hooks': [make_progress_hook(download_id)],
                    'postprocessor_hooks': [make_postprocessor_hook(download_id, override_title, override_artist, override_cover)],
                    'retries': 10,
                    'fragment_retries': 10
                }
                
                if is_missav:
                    from urllib.parse import urlparse
                    ydl_opts['referer'] = f"https://{urlparse(target_url).netloc}/"

                if subtitles == 'true':
                    ydl_opts.update({
                        'writesubtitles': True,
                        'writeautomaticsub': True,
                        'embedsubtitles': True,
                        'postprocessors': [{'key': 'FFmpegEmbedSubtitle'}]
                    })

                if format_type == 'mp3':
                    ydl_opts.update({
                        'format': 'bestaudio/best',
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': bitrate,
                        }],
                    })
                elif format_type == 'm4a':
                    ydl_opts.update({
                        'format': 'bestaudio[ext=m4a]/bestaudio/best',
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'm4a',
                        }],
                    })
                elif format_type == 'flac':
                    ydl_opts.update({
                        'format': 'bestaudio/best',
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'flac',
                        }],
                    })
                elif format_type == 'wav':
                    ydl_opts.update({
                        'format': 'bestaudio/best',
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'wav',
                        }],
                    })
                elif format_type.startswith('mp4_'):
                    try:
                        height = int(format_type.split('_')[1])
                    except (IndexError, ValueError):
                        height = 720
                    ydl_opts.update({
                        'format': f'bestvideo[height<={height}]+bestaudio/best[height<={height}]/best[height<={height}]/best',
                        'merge_output_format': video_container
                    })
                else: # mp4_720
                    ydl_opts.update({
                        'format': 'best[ext=mp4][height<=720]/best[height<=720]/best',
                        'merge_output_format': video_container
                    })
                
                try:
                    track_label = override_title or final_url[:80]
                    logging.info(f"Batch [{batch_idx+1}/{total_batch}] Downloading: {track_label}")
                    download_url_with_fallback(ydl_opts, final_url)
                    completed_batch += 1
                    logging.info(f"Batch [{batch_idx+1}/{total_batch}] Completed: {track_label}")
                except Exception as track_err:
                    failed_batch += 1
                    logging.error(f"Batch [{batch_idx+1}/{total_batch}] Failed: {track_label} - {track_err}")
                    # Continue to next track instead of stopping the entire batch
                    continue
        
        # Complete
        download_progress[download_id] = {
            'status': 'completed',
            'percent': 100,
            'speed': 'Done',
            'eta': '00:00'
        }
        _schedule_cleanup(download_id, delay=10)
    except Exception as e:
        err_msg = str(e)
        if "cancelled by user" in err_msg or "Download cancelled by user" in err_msg:
            download_progress[download_id] = {
                'status': 'cancelled',
                'message': 'การดาวน์โหลดถูกยกเลิกโดยผู้ใช้งาน'
            }
        else:
            # Sanitize error message: remove local paths and stack traces
            safe_msg = re.sub(r'[A-Z]:\\[\w\\. ]+', '[path]', err_msg)
            download_progress[download_id] = {
                'status': 'error',
                'message': safe_msg
            }
        _schedule_cleanup(download_id, delay=10)

@app.route('/download_progress/<download_id>')
def download_progress_stream(download_id):
    def generate():
        import time
        max_wait = 600  # Timeout: 10 minutes max to prevent infinite SSE loops
        elapsed = 0
        while elapsed < max_wait:
            time.sleep(0.5)
            elapsed += 0.5
            state = download_progress.get(download_id)
            if not state:
                yield "data: {\"status\": \"starting\", \"percent\": 0}\n\n"
                continue
            
            yield f"data: {json.dumps(state)}\n\n"
            
            if state['status'] in ['completed', 'error', 'cancelled']:
                break
        else:
            yield 'data: {"status": "error", "message": "Connection timed out after 10 minutes"}\n\n'
    return Response(generate(), mimetype='text/event-stream')

@app.route('/shutdown', methods=['POST'])
def shutdown():
    def kill_process():
        import time
        import os
        import logging
        logging.info("Initiating clean shutdown sequence...")
        
        # 1. Cancel all active downloads to terminate yt-dlp threads
        active_count = 0
        with _progress_lock:
            for d_id in list(download_progress.keys()):
                if download_progress[d_id].get('status') in ['starting', 'downloading', 'processing']:
                    cancelled_downloads.add(d_id)
                    active_count += 1
        
        if active_count > 0:
            logging.info(f"Cancellation requested for {active_count} active downloads. Waiting for release...")
        
        # 2. Wait for yt-dlp threads to abort and release file locks
        time.sleep(1.5)
        
        # 3. Clean up stale temporary files (.part, .ytdl, etc.)
        try:
            cleanup_temp_files()
            logging.info("Clean shutdown: Stale temporary files cleaned successfully.")
        except Exception as e:
            logging.error(f"Error during clean shutdown file cleanup: {e}")
            
        logging.info("Shutdown sequence complete. Exiting process.")
        # Exit cleanly
        os._exit(0)

    import threading
    threading.Thread(target=kill_process).start()
    return jsonify({'message': 'Server shutting down...'})

@app.route('/api/ping', methods=['POST'])
def ping():
    global last_ping_time
    import time
    last_ping_time = time.time()
    return jsonify({'status': 'ok'})

@app.route('/engine_status', methods=['GET'])
def engine_status():
    try:
        import json
        current_version = yt_dlp.version.__version__
        is_updated = os.path.exists(os.path.join(app_path, 'bin', 'yt-dlp-update'))
        
        # Check latest version on PyPI
        latest_version = current_version
        try:
            req = urllib.request.Request("https://pypi.org/pypi/yt-dlp/json", headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as res:
                pypi_data = json.loads(res.read().decode('utf-8'))
                latest_version = pypi_data['info']['version']
        except Exception:
            pass # Network issue or offline, fallback to current_version

        # Read version from downloaded update folder if exists
        update_version = None
        update_path = os.path.join(app_path, 'bin', 'yt-dlp-update')
        if os.path.exists(update_path):
            try:
                ver_file = os.path.join(update_path, 'yt_dlp', 'version.py')
                if os.path.exists(ver_file):
                    with open(ver_file, 'r', encoding='utf-8') as vf:
                        ver_content = vf.read()
                        match = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", ver_content)
                        if match:
                            update_version = match.group(1)
            except Exception:
                pass

        update_pending_restart = False
        if update_version and latest_version and update_version == latest_version and current_version != latest_version:
            update_pending_restart = True
            
        return jsonify({
            'current_version': current_version,
            'latest_version': latest_version,
            'is_updated': is_updated,
            'needs_update': current_version != latest_version,
            'update_pending_restart': update_pending_restart,
            'auto_update': auto_update_status
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/revert_engine', methods=['POST'])
def revert_engine():
    try:
        update_path = os.path.join(app_path, 'bin', 'yt-dlp-update')
        if os.path.exists(update_path):
            shutil.rmtree(update_path, ignore_errors=True)
            return jsonify({'message': 'ล้างการอัปเดตและคืนค่าเป็นเครื่องยนต์เริ่มต้นเรียบร้อยแล้ว กรุณาเริ่มโปรแกรมใหม่เพื่อใช้การตั้งค่านี้'})
        return jsonify({'message': 'คุณกำลังใช้งานเครื่องยนต์เริ่มต้นอยู่แล้ว'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/update_engine', methods=['POST'])
def update_engine():
    try:
        import json
        
        # 1. Fetch PyPI data
        req = urllib.request.Request("https://pypi.org/pypi/yt-dlp/json", headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as res:
            pypi_data = json.loads(res.read().decode('utf-8'))
            
        latest_version = pypi_data['info']['version']
        
        # 2. Find download url of the wheel file
        urls = pypi_data['urls']
        whl_url = None
        for url_info in urls:
            if url_info['filename'].endswith('.whl'):
                whl_url = url_info['url']
                break
                
        if not whl_url:
            raise Exception("Could not find a valid release package on PyPI.")
            
        # 3. Download package
        temp_dir = tempfile.gettempdir()
        temp_file_path = os.path.join(temp_dir, "yt_dlp_update.whl")
        
        req_dl = urllib.request.Request(whl_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req_dl, timeout=60) as response_dl:
            with open(temp_file_path, 'wb') as out_file:
                out_file.write(response_dl.read())
                
        # 4. Extract yt_dlp package
        target_dir = os.path.join(app_path, 'bin', 'yt-dlp-update')
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)
            
        with zipfile.ZipFile(temp_file_path, 'r') as zip_ref:
            for file in zip_ref.namelist():
                if file.startswith('yt_dlp/'):
                    zip_ref.extract(file, target_dir)
                    
        # Cleanup temp file
        try:
            os.remove(temp_file_path)
        except Exception:
            pass
            
        return jsonify({'message': f'Engine updated successfully to v{latest_version}. Please restart the application.'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
@app.route('/api/cancel_download', methods=['POST'])
def cancel_download():
    download_id = request.form.get('download_id')
    if download_id:
        cancelled_downloads.add(download_id)
        logging.info(f"Cancellation requested for download: {download_id}")
        return jsonify({'status': 'cancel_requested'})
    return jsonify({'error': 'Missing download_id'}), 400
@app.route('/api/logs', methods=['GET'])
def get_logs():
    try:
        log_file = os.path.join(app_path, 'app.log')
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                return jsonify({'logs': ''.join(lines[-150:])})
        return jsonify({'logs': 'Log file not found.'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def cleanup_temp_files():
    try:
        save_dir = config.get('save_folder')
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

if __name__ == '__main__':
    cleanup_temp_files()

    port = 5000
    import threading
    
    # Run Flask in background daemon thread
    flask_thread = threading.Thread(
        target=lambda: app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False),
        daemon=True
    )
    flask_thread.start()
    
    # Launch PyWebView desktop GUI window
    import webview
    logging.info("Opening PyWebView desktop window...")
    webview.create_window(
        'Phoebe Downloader',
        f"http://127.0.0.1:{port}",
        width=1280,
        height=820,
        min_size=(1024, 768)
    )
    webview.start()
    
    # Clean shutdown sequence after WebView window is closed
    logging.info("WebView window closed. Initiating clean shutdown sequence...")
    with _progress_lock:
        for d_id in list(download_progress.keys()):
            if download_progress[d_id].get('status') in ['starting', 'downloading', 'processing']:
                cancelled_downloads.add(d_id)
                
    import time
    time.sleep(1.5)
    try:
        cleanup_temp_files()
    except Exception:
        pass
    logging.info("Clean shutdown completed. Exiting process.")
    os._exit(0)
