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

def extract_info_with_fallback(target_url, ydl_opts):
    if 'youtube.com' not in target_url and 'youtu.be' not in target_url:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(target_url, download=False)
            
    detected_browsers = []
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
            detected_browsers.append(name)
    detected_browsers.append(None)
    
    last_err = None
    for browser in detected_browsers:
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
                logging.warning(f"Failed to fetch info using cookies from browser '{browser}': {e}. Trying next fallback...")
                last_err = e
                continue
            else:
                raise e
    raise last_err

def download_url_with_fallback(ydl_opts, target_url):
    if 'youtube.com' not in target_url and 'youtu.be' not in target_url:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([target_url])
            return

    detected_browsers = []
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
            detected_browsers.append(name)
    detected_browsers.append(None)
    
    last_err = None
    for browser in detected_browsers:
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
                logging.warning(f"Failed to download using cookies from browser '{browser}': {e}. Trying next fallback...")
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
download_progress = {}

cancelled_downloads = set()

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
            recommendation = "💡 เสียงต้นฉบับบน YouTube เป็น Opus คุณภาพสูง แนะนำให้เลือก M4A Original เพื่อดาวน์โหลดเร็วและไม่เสียคุณภาพ หรือเลือก MP3 320kbps / Lossless FLAC เพื่อแปลงเป็นฟอร์แมตยอดนิยม"
        elif 'mp4a' in codec_lower or 'aac' in codec_lower:
            if max_audio_bitrate >= 192:
                recommendation = f"💡 เสียงต้นฉบับเป็น AAC คุณภาพสูง ({max_audio_bitrate} kbps) แนะนำให้เลือก M4A Original หรือ MP3 320kbps เพื่อคงคุณภาพความละเอียดดนตรีไว้ครบถ้วน"
            else:
                recommendation = f"💡 เสียงต้นฉบับเป็น AAC ความละเอียดปกติ ({max_audio_bitrate} kbps) แนะนำให้เลือก M4A Original เพื่อบันทึกเสียงสดต้นฉบับได้ทันทีโดยไม่ต้องแปลงสัญญาณใหม่ หรือเลือก MP3 192kbps"
        elif 'mp3' in codec_lower:
            recommendation = f"💡 เสียงต้นฉบับเป็น MP3 ({max_audio_bitrate} kbps) แนะนำให้ดาวน์โหลดเป็น MP3 320kbps หรือ M4A Original เพื่อให้ได้เสียงที่คมชัดที่สุดตามคุณภาพดั้งเดิม"
        else:
            recommendation = f"💡 เสียงต้นฉบับเป็นฟอร์แมต {best_audio_codec.upper()} แนะนำให้ดาวน์โหลดเป็น M4A Original หรือ MP3 320kbps เพื่อการประมวลผลและการใช้งานที่เสถียรที่สุด"

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
                req = urllib.request.Request(thumbnail_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=10) as response:
                    cover_bytes = response.read()
            except Exception as e:
                logging.warning(f"Failed to download cover art from {thumbnail_url}: {e}")

        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.mp3':
            from mutagen.mp3 import MP3, HeaderNotFoundError
            from mutagen.id3 import ID3, APIC, TIT2, TPE1, error
            audio = None
            tags = None
            try:
                audio = MP3(file_path, ID3=ID3)
                try:
                    audio.add_tags()
                except Exception:
                    pass
                tags = audio.tags
            except HeaderNotFoundError:
                try:
                    audio = ID3(file_path)
                    tags = audio
                except Exception:
                    audio = ID3()
                    tags = audio
            
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
                audio.save(file_path)
                logging.info(f"Successfully tagged MP3 file: {file_path}")
        elif ext in ['.m4a', '.mp4']:
            from mutagen.mp4 import MP4, MP4Cover
            audio = MP4(file_path)
            if title:
                audio["\xa9nam"] = title
            if artist:
                audio["\xa9ART"] = artist
            if cover_bytes:
                audio["covr"] = [MP4Cover(cover_bytes, imageformat=MP4Cover.FORMAT_JPEG)]
            audio.save()
            logging.info(f"Successfully tagged M4A file: {file_path}")
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

        def make_postprocessor_hook(d_id):
            def hook(d):
                if d_id in cancelled_downloads:
                    raise Exception("Download cancelled by user")
                if d.get('status') == 'finished' and embed_metadata == 'true':
                    filename = d.get('filepath') or d.get('filename')
                    if not filename:
                        info_temp = d.get('info_dict', {})
                        filename = info_temp.get('filepath') or info_temp.get('_filename')
                    
                    if filename and os.path.exists(filename):
                        ext = os.path.splitext(filename)[1].lower()
                        if ext in ['.mp3', '.m4a', '.mp4', '.mkv', '.webm', '.flac', '.wav']:
                            info = d.get('info_dict', {})
                            title = info.get('title')
                            artist = info.get('uploader') or info.get('artist')
                            
                            thumbnail = info.get('thumbnail')
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
            for target_url in urls:
                if download_id in cancelled_downloads:
                    raise Exception("Download cancelled by user")
                is_missav = 'missav.' in target_url
                final_url = target_url
                custom_title = None

                if is_missav:
                    m3u8_url, custom_title = extract_missav(target_url)
                    if not m3u8_url:
                        continue
                    final_url = m3u8_url

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
                
                if is_missav:
                    from urllib.parse import urlparse
                    ydl_opts['referer'] = f"https://{urlparse(target_url).netloc}/"
                    if custom_title:
                        safe_title = re.sub(r'[\\/*?:"<>|]', "", custom_title)
                        safe_title = safe_title[:100].strip()
                        output_template = os.path.join(save_dir, f"{safe_title}.%(ext)s")
                        ydl_opts['outtmpl'] = output_template

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
                
                download_url_with_fallback(ydl_opts, final_url)
        
        # Complete
        download_progress[download_id] = {
            'status': 'completed',
            'percent': 100,
            'speed': 'Done',
            'eta': '00:00'
        }
    except Exception as e:
        err_msg = str(e)
        if "cancelled by user" in err_msg or "Download cancelled by user" in err_msg:
            download_progress[download_id] = {
                'status': 'cancelled',
                'message': 'การดาวน์โหลดถูกยกเลิกโดยผู้ใช้งาน'
            }
        else:
            download_progress[download_id] = {
                'status': 'error',
                'message': err_msg
            }

@app.route('/download_progress/<download_id>')
def download_progress_stream(download_id):
    def generate():
        while True:
            import time
            time.sleep(0.5)
            state = download_progress.get(download_id)
            if not state:
                yield "data: {\"status\": \"starting\", \"percent\": 0}\n\n"
                continue
            
            yield f"data: {json.dumps(state)}\n\n"
            
            if state['status'] in ['completed', 'error', 'cancelled']:
                break
    return Response(generate(), mimetype='text/event-stream')

@app.route('/shutdown', methods=['POST'])
def shutdown():
    def kill_process():
        import time
        import os
        import signal
        time.sleep(1.0)
        os.kill(os.getpid(), signal.SIGTERM)
        
    import threading
    threading.Thread(target=kill_process).start()
    return jsonify({'message': 'Server shutting down...'})

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
            
        return jsonify({
            'current_version': current_version,
            'latest_version': latest_version,
            'is_updated': is_updated,
            'needs_update': current_version != latest_version
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
    def open_browser(port):
        import time
        import webbrowser
        time.sleep(1.5)
        webbrowser.open(f"http://127.0.0.1:{port}")

    port = 5000
    import threading
    threading.Thread(target=open_browser, args=(port,), daemon=True).start()
    app.run(host='127.0.0.1', port=port, debug=False)
