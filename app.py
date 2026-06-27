import os
import re
import sys
import uuid
import shutil
import zipfile
import urllib.request
import tempfile
import json
from flask import Flask, render_template, request, jsonify, send_file, Response

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

# Dynamic Engine Loading
update_path = os.path.join(app_path, 'bin', 'yt-dlp-update')
if os.path.exists(update_path):
    sys.path.insert(0, update_path)
    print(f"Dynamically loaded updated yt-dlp engine from: {update_path}")

import yt_dlp
from curl_cffi import requests as curl_requests

app = Flask(__name__)
app.template_folder = template_folder
app.static_folder = static_folder

DOWNLOAD_FOLDER = os.path.join(app_path, 'downloads')
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# Global dictionary to track active download states
download_progress = {}

# FFmpeg setup
BIN_FOLDER = os.path.join(app_path, 'bin')
if os.path.exists(os.path.join(BIN_FOLDER, 'ffmpeg.exe')):
    os.environ["PATH"] += os.pathsep + BIN_FOLDER
    print(f"Added local FFmpeg from {BIN_FOLDER}")

# Middleware to check FFmpeg requirements
@app.before_request
def check_ffmpeg():
    # Exempt setup, shutdown and static files
    if request.path.startswith('/setup') or request.path.startswith('/static') or request.path == '/shutdown':
        return
        
    ffmpeg_path = os.path.join(BIN_FOLDER, 'ffmpeg.exe')
    if not os.path.exists(ffmpeg_path):
        from flask import redirect, url_for
        return redirect(url_for('setup_page'))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/setup')
def setup_page():
    return render_template('setup.html')

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
        print(f"MissAV extraction error: {e}")
        return None, None

@app.route('/info', methods=['POST'])
def get_info():
    url = request.form.get('url')
    if not url:
        return jsonify({'error': 'Please provide a URL'}), 400

    try:
        # Check if multiple URLs separated by commas or newlines
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

        is_missav = 'missav.' in url
        target_url = url
        custom_title = None

        if is_missav:
            m3u8_url, custom_title = extract_missav(url)
            if not m3u8_url:
                return jsonify({'error': 'Failed to extract video from MissAV.'}), 400
            target_url = m3u8_url

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'nocache': True,
        }
        
        if is_missav:
            from urllib.parse import urlparse
            ydl_opts['referer'] = f"https://{urlparse(url).netloc}/"

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(target_url, download=False)
            
            # Check if playlist
            if info.get('_type') == 'playlist':
                entries = list(info.get('entries', []))
                return jsonify({
                    'title': f"Playlist: {info.get('title', 'Playlist')}",
                    'thumbnail': entries[0].get('thumbnail') if entries and entries[0] else '',
                    'duration': f"{len(entries)} items",
                    'uploader': info.get('uploader', 'Unknown'),
                    'resolutions': ['720p', '1080p', 'mp3'],
                    'url': url
                })

            # Extract available resolutions
            formats = info.get('formats', [])
            resolutions = set()
            for f in formats:
                if f.get('vcodec') != 'none' and f.get('height'):
                    resolutions.add(f.get('height'))
            
            available_qualities = []
            if 2160 in resolutions: available_qualities.append('2160p')
            if 1080 in resolutions: available_qualities.append('1080p')
            if 720 in resolutions: available_qualities.append('720p')
            available_qualities.append('mp3')

            return jsonify({
                'title': custom_title if custom_title else info.get('title'),
                'thumbnail': info.get('thumbnail'),
                'duration': info.get('duration_string', ''),
                'uploader': info.get('uploader', 'Unknown'),
                'resolutions': available_qualities,
                'url': url
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/prepare_download', methods=['POST'])
def prepare_download():
    url = request.form.get('url')
    format_type = request.form.get('format_type')
    bitrate = request.form.get('bitrate', '192')
    subtitles = request.form.get('subtitles', 'false')
    download_id = str(uuid.uuid4())
    return render_template('downloading.html', url=url, format_type=format_type, bitrate=bitrate, subtitles=subtitles, download_id=download_id)

@app.route('/download_start', methods=['POST'])
def download_start():
    url = request.form.get('url')
    format_type = request.form.get('format_type')
    bitrate = request.form.get('bitrate', '192')
    subtitles = request.form.get('subtitles', 'false')
    download_id = request.form.get('download_id')

    if not url or not download_id:
        return jsonify({'error': 'Missing parameters'}), 400

    # Initialize download status
    download_progress[download_id] = {
        'status': 'starting',
        'percent': 0,
        'speed': '0 KB/s',
        'eta': 'Unknown'
    }

    # Start the downloading thread
    import threading
    threading.Thread(
        target=run_download_thread,
        args=(download_id, url, format_type, bitrate, subtitles),
        daemon=True
    ).start()

    return jsonify({'status': 'started'})

def run_download_thread(download_id, url, format_type, bitrate, subtitles):
    try:
        session_dir = os.path.join(DOWNLOAD_FOLDER, download_id)
        os.makedirs(session_dir, exist_ok=True)
        
        urls = [u.strip() for u in url.replace('\n', ',').split(',') if u.strip()]
        
        # Check if first URL is a playlist
        is_playlist = False
        if len(urls) == 1:
            ydl_opts_check = {'quiet': True, 'extract_flat': True, 'nocache': True}
            with yt_dlp.YoutubeDL(ydl_opts_check) as ydl:
                check_info = ydl.extract_info(urls[0], download=False)
                if check_info.get('_type') == 'playlist':
                    is_playlist = True

        # Custom progress hook closure that captures download_id
        def make_progress_hook(d_id):
            def hook(d):
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
                    
                    download_progress[d_id] = {
                        'status': 'downloading',
                        'percent': percent_val,
                        'speed': speed_str,
                        'eta': eta_str
                    }
                elif d['status'] == 'finished':
                    download_progress[d_id] = {
                        'status': 'processing',
                        'percent': 99,
                        'speed': 'Processing...',
                        'eta': '00:00'
                    }
            return hook

        output_template = os.path.join(session_dir, '%(title)s.%(ext)s')
        ydl_opts = {
            'outtmpl': output_template,
            'quiet': True,
            'nocache': True,
            'progress_hooks': [make_progress_hook(download_id)]
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
            elif format_type == 'mp4_1080':
                ydl_opts.update({
                    'format': 'bestvideo[height=1080]+bestaudio/best[height=1080]',
                    'merge_output_format': 'mp4'
                })
            elif format_type == 'mp4_2160':
                ydl_opts.update({
                    'format': 'bestvideo[height=2160]+bestaudio/best[height=2160]',
                    'merge_output_format': 'mp4'
                })
            else:
                ydl_opts.update({
                    'format': 'best[ext=mp4][height<=720]/best[height<=720]/best',
                })
                
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([urls[0]])
        else:
            # Batch URLs
            for target_url in urls:
                is_missav = 'missav.' in target_url
                final_url = target_url
                custom_title = None

                if is_missav:
                    m3u8_url, custom_title = extract_missav(target_url)
                    if not m3u8_url:
                        continue
                    final_url = m3u8_url

                output_template = os.path.join(session_dir, '%(title)s.%(ext)s')
                
                ydl_opts = {
                    'outtmpl': output_template,
                    'quiet': True,
                    'nocache': True,
                    'progress_hooks': [make_progress_hook(download_id)]
                }
                
                if is_missav:
                    from urllib.parse import urlparse
                    ydl_opts['referer'] = f"https://{urlparse(target_url).netloc}/"
                    if custom_title:
                        safe_title = re.sub(r'[\\/*?:"<>|]', "", custom_title)
                        safe_title = safe_title[:100].strip()
                        output_template = os.path.join(session_dir, f"{safe_title}.%(ext)s")
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
                elif format_type == 'mp4_1080':
                    ydl_opts.update({
                        'format': 'bestvideo[height=1080]+bestaudio/best[height=1080]',
                        'merge_output_format': 'mp4'
                    })
                elif format_type == 'mp4_2160':
                    ydl_opts.update({
                        'format': 'bestvideo[height=2160]+bestaudio/best[height=2160]',
                        'merge_output_format': 'mp4'
                    })
                else: # mp4_720
                    ydl_opts.update({
                        'format': 'best[ext=mp4][height<=720]/best[height<=720]/best',
                    })
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([final_url])
        
        # Scan downloaded files
        downloaded_files = []
        for root, dirs, files in os.walk(session_dir):
            for file in files:
                if not file.endswith(('.part', '.ytdl', '.temp')):
                    downloaded_files.append(os.path.join(root, file))
                
        if not downloaded_files:
            raise Exception("No files were downloaded.")

        # Update status to completed
        download_progress[download_id] = {
            'status': 'completed',
            'percent': 100,
            'speed': 'Done',
            'eta': '00:00'
        }
    except Exception as e:
        download_progress[download_id] = {
            'status': 'error',
            'message': str(e)
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
            
            if state['status'] in ['completed', 'error']:
                break
    return Response(generate(), mimetype='text/event-stream')

@app.route('/download_file/<download_id>')
def download_file(download_id):
    try:
        session_dir = os.path.join(DOWNLOAD_FOLDER, download_id)
        downloaded_files = []
        for root, dirs, files in os.walk(session_dir):
            for file in files:
                if not file.endswith(('.part', '.ytdl', '.temp')):
                    downloaded_files.append(os.path.join(root, file))
                    
        if not downloaded_files:
            return "Error: No downloaded files found.", 404
            
        # Single file
        if len(downloaded_files) == 1:
            filepath = downloaded_files[0]
            
            def delayed_cleanup(dir_path):
                import time
                time.sleep(15)
                try:
                    if os.path.exists(dir_path):
                        shutil.rmtree(dir_path)
                except Exception as e:
                    print(f"Error cleaning up folder {dir_path}: {e}")
            
            import threading
            threading.Thread(target=delayed_cleanup, args=(session_dir,)).start()
            return send_file(filepath, as_attachment=True)
            
        else:
            # Batch ZIP file
            zip_filename = os.path.join(DOWNLOAD_FOLDER, f"{download_id}.zip")
            with zipfile.ZipFile(zip_filename, 'w') as zipf:
                for file in downloaded_files:
                    zipf.write(file, os.path.basename(file))
                    
            def delayed_cleanup_all(dir_path, zip_path):
                import time
                time.sleep(20)
                try:
                    if os.path.exists(dir_path):
                        shutil.rmtree(dir_path)
                    if os.path.exists(zip_path):
                        os.remove(zip_path)
                except Exception as e:
                    print(f"Error cleaning up files: {e}")
                    
            import threading
            threading.Thread(target=delayed_cleanup_all, args=(session_dir, zip_filename)).start()
            return send_file(zip_filename, as_attachment=True, download_name="downloader_batch.zip")
            
    except Exception as e:
        return str(e), 500

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

if __name__ == '__main__':
    def open_browser(port):
        import time
        import webbrowser
        time.sleep(1.5)
        webbrowser.open(f"http://127.0.0.1:{port}")

    port = 5000
    import threading
    threading.Thread(target=open_browser, args=(port,), daemon=True).start()
    app.run(host='127.0.0.1', port=port, debug=False)
