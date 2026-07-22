import os
import re
import sys
import json
import uuid
import shutil
import base64
import logging
import urllib.request
import tempfile
import zipfile
import winreg
import threading
from curl_cffi import requests as curl_requests
import yt_dlp

# Application version
APP_VERSION = "2.3.0"

# Normalize version string for integer tuple comparison
def normalize_version(version_str):
    if not version_str:
        return (0, 0, 0)
    parts = re.findall(r'\d+', str(version_str))
    return tuple(int(p) for p in parts)

def format_bytes(b):
    if b is None or b == 0:
        return '0 B'
    for unit in ['B', 'KB', 'MB', 'GB']:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"

def get_windows_downloads_path():
    try:
        sub_key = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub_key) as key:
            path = winreg.QueryValueEx(key, '{374DE290-123F-4565-9164-39C4925E467B}')[0]
            return os.path.normpath(path)
    except Exception:
        return os.path.normpath(os.path.join(os.path.expanduser('~'), 'Downloads'))

def _detect_browsers():
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
    detected.append(None)
    return detected

def _is_youtube_url(target_url):
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

def extract_missav(url):
    try:
        response = curl_requests.get(url, impersonate="chrome120", timeout=15)
        html = response.text
        title_match = re.search(r'<meta property="og:title" content="([^"]+)"', html)
        if not title_match:
            title_match = re.search(r'<meta property="og:title"\s+content="([^"]+)"', html)
        title = title_match.group(1) if title_match else "MissAV Video"
        title = title.replace(" - MissAV", "").replace(" - missav", "").strip()

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
    if 'nd=1' not in url:
        url += '&nd=1' if '?' in url else '?nd=1'
    playlist_id_match = re.search(r'/playlist/([a-zA-Z0-9]+)', url)
    if not playlist_id_match:
        raise Exception("Invalid Spotify playlist URL")
    playlist_id = playlist_id_match.group(1)
    
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
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
        if not item_v2: continue
        track_data = item_v2.get("data", {})
        if not track_data or track_data.get("__typename") != "Track": continue
            
        track_name = track_data.get("name", "Unknown Track")
        artists_items = track_data.get("artists", {}).get("items", [])
        artist_names = ", ".join([a.get("profile", {}).get("name", "") for a in artists_items if a.get("profile")]) or "Unknown Artist"
        
        cover_sources = track_data.get("albumOfTrack", {}).get("coverArt", {}).get("sources", [])
        cover_url = max(cover_sources, key=lambda x: x.get("width", 0)).get("url", "") if cover_sources else ""
            
        duration_dict = track_data.get("duration", {})
        duration_ms = duration_dict.get("totalMilliseconds") or duration_dict.get("milliseconds") or 0 if isinstance(duration_dict, dict) else int(duration_dict or 0)
        duration_secs = duration_ms // 1000
        
        payload = {'title': track_name, 'artist': artist_names, 'cover': cover_url}
        encoded_payload = base64.b64encode(json.dumps(payload).encode('utf-8')).decode('utf-8')
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
    if 'nd=1' not in url:
        url += '&nd=1' if '?' in url else '?nd=1'
    track_id_match = re.search(r'/track/([a-zA-Z0-9]+)', url)
    if not track_id_match:
        raise Exception("Invalid Spotify track URL")
    track_id = track_id_match.group(1)
    
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
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
    artist_names = ", ".join([a.get("profile", {}).get("name", "") for a in artists_items if a.get("profile")]) or "Unknown Artist"
    
    cover_sources = track_data.get("albumOfTrack", {}).get("coverArt", {}).get("sources", [])
    cover_url = max(cover_sources, key=lambda x: x.get("width", 0)).get("url", "") if cover_sources else ""
        
    duration_dict = track_data.get("duration", {})
    duration_ms = duration_dict.get("totalMilliseconds") or duration_dict.get("milliseconds") or 0 if isinstance(duration_dict, dict) else int(duration_dict or 0)
    duration_secs = duration_ms // 1000
    
    payload = {'title': track_name, 'artist': artist_names, 'cover': cover_url}
    encoded_payload = base64.b64encode(json.dumps(payload).encode('utf-8')).decode('utf-8')
    virtual_url = f"spotify_track:{encoded_payload}"
    
    return {
        'title': f"{track_name} - {artist_names}",
        'thumbnail': cover_url,
        'duration': f"{duration_secs // 60}:{duration_secs % 60:02d}" if duration_secs > 0 else "",
        'uploader': artist_names,
        'resolutions': ['mp3', 'm4a', 'flac', 'wav'],
        'url': virtual_url
    }

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
            from mutagen.id3 import ID3, APIC, TIT2, TPE1
            try:
                try: tags = ID3(file_path)
                except Exception: tags = ID3()
                if title: tags.add(TIT2(encoding=3, text=title))
                if artist: tags.add(TPE1(encoding=3, text=artist))
                if cover_bytes: tags.add(APIC(encoding=3, mime='image/jpeg', type=3, desc=u'Cover', data=cover_bytes))
                tags.save(file_path, v2_version=3)
            except Exception as mp3_err: logging.error(f"Error tagging MP3 {file_path}: {mp3_err}")
        elif ext == '.flac':
            from mutagen.flac import FLAC, Picture
            try:
                audio = FLAC(file_path)
                if title: audio["title"] = title
                if artist: audio["artist"] = artist
                if cover_bytes:
                    pic = Picture()
                    pic.data = cover_bytes; pic.type = 3; pic.mime = "image/jpeg"; pic.desc = u"Cover"
                    audio.clear_pictures(); audio.add_picture(pic)
                audio.save()
            except Exception as flac_err: logging.error(f"Error tagging FLAC {file_path}: {flac_err}")
        elif ext == '.wav':
            from mutagen.wave import WAVE
            from mutagen.id3 import ID3, APIC, TIT2, TPE1
            try:
                audio = WAVE(file_path)
                try: audio.add_tags()
                except Exception: pass
                tags = audio.tags
                if tags is not None:
                    if title: tags.add(TIT2(encoding=3, text=title))
                    if artist: tags.add(TPE1(encoding=3, text=artist))
                    if cover_bytes: tags.add(APIC(encoding=3, mime='image/jpeg', type=3, desc=u'Cover', data=cover_bytes))
                    audio.save()
            except Exception as wav_err: logging.error(f"Error tagging WAV {file_path}: {wav_err}")
        elif ext in ['.m4a', '.mp4']:
            from mutagen.mp4 import MP4, MP4Cover
            try:
                audio = MP4(file_path)
                if title: audio["\xa9nam"] = title
                if artist: audio["\xa9ART"] = artist
                if cover_bytes and ext == '.m4a':
                    audio["covr"] = [MP4Cover(cover_bytes, imageformat=MP4Cover.FORMAT_JPEG)]
                audio.save()
            except Exception as mp4_err: logging.error(f"Error tagging {ext.upper()} {file_path}: {mp4_err}")
    except Exception as e:
        logging.error(f"Error in embed_metadata_to_file for {file_path}: {e}", exc_info=True)


class PyWebViewAPI:
    def __init__(self, app_path):
        self.app_path = app_path
        self._window = None
        self.config = {
            'save_folder': get_windows_downloads_path()
        }
        self.cancelled_downloads = set()
        self.auto_update_status = {'status': 'idle', 'message': ''}
        self.app_update_downloading = False
        self.app_update_progress = 0
        self.app_update_status = "idle"
        self.app_update_error = ""
        self.downloaded_installer_path = ""
        self.is_updating_engine = False
        self._last_push_time = {}
        self._push_lock = threading.Lock()
        self.active_downloads = set()
        self._download_lock = threading.Lock()
        self.is_shutting_down = False

    def set_window(self, window):
        self._window = window

    # --------------------------------------------------
    # Settings & Folder Management
    # --------------------------------------------------
    def get_settings(self):
        return self.config

    def select_folder(self, manual_path=None):
        if manual_path:
            manual_path = os.path.normpath(manual_path)
            if os.path.isdir(manual_path):
                self.config['save_folder'] = manual_path
                return {'save_folder': manual_path}
            else:
                return {'error': 'Invalid directory path.'}

        if self._window:
            import webview
            result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
            if result and len(result) > 0:
                selected_path = os.path.normpath(result[0])
                self.config['save_folder'] = selected_path
                return {'save_folder': selected_path}

        return {'save_folder': self.config['save_folder']}

    def open_folder(self):
        try:
            folder_path = self.config.get('save_folder')
            if os.path.exists(folder_path):
                os.startfile(folder_path)
                return {'status': 'opened'}
            else:
                return {'error': 'Folder path does not exist.'}
        except Exception as e:
            return {'error': str(e)}

    def get_clipboard(self):
        try:
            import ctypes
            CF_UNICODETEXT = 13
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            
            if user32.OpenClipboard(None):
                try:
                    h_cd = user32.GetClipboardData(CF_UNICODETEXT)
                    if h_cd:
                        ptr = kernel32.GlobalLock(h_cd)
                        if ptr:
                            try:
                                text = ctypes.wstring_at(ptr)
                                return {'text': text}
                            finally:
                                kernel32.GlobalUnlock(h_cd)
                finally:
                    user32.CloseClipboard()
        except Exception:
            pass

        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            text = root.clipboard_get()
            root.destroy()
            return {'text': text}
        except Exception:
            return {'text': ''}

    def get_logs(self):
        try:
            log_file = os.path.join(self.app_path, 'app.log')
            if os.path.exists(log_file):
                with open(log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    return {'logs': ''.join(lines[-150:])}
            return {'logs': 'Log file not found.'}
        except Exception as e:
            return {'error': str(e)}

    # --------------------------------------------------
    # Link Analysis & Info Extraction
    # --------------------------------------------------
    def process_input(self, url):
        if not url or not url.strip():
            return {'error': 'Please provide a URL or search term.'}

        try:
            urls = [u.strip() for u in url.replace('\n', ',').split(',') if u.strip()]
            
            if len(urls) > 1:
                return {
                    'title': f'Batch Download ({len(urls)} links)',
                    'thumbnail': 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=500',
                    'duration': 'N/A',
                    'uploader': 'Batch Mode',
                    'resolutions': ['720p', '1080p', 'mp3'],
                    'url': url
                }

            target_url = urls[0]
            if 'spotify.com/playlist/' in target_url:
                return parse_spotify_playlist(target_url)
            elif 'spotify.com/track/' in target_url:
                return parse_spotify_track(target_url)

            if not target_url.startswith('http://') and not target_url.startswith('https://'):
                target_url = f"ytsearch1:{target_url}"

            is_missav = 'missav.' in target_url
            custom_title = None

            if is_missav:
                m3u8_url, custom_title = extract_missav(target_url)
                if not m3u8_url:
                    return {'error': 'Failed to extract video from MissAV.'}
                target_url = m3u8_url

            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'nocache': True
            }
            if 'list=' in target_url or '/playlist' in target_url:
                ydl_opts['extract_flat'] = True
            if is_missav:
                from urllib.parse import urlparse
                ydl_opts['referer'] = f"https://{urlparse(target_url).netloc}/"

            info = extract_info_with_fallback(target_url, ydl_opts)
                
            if info.get('_type') == 'playlist':
                entries = list(info.get('entries', []))
                if target_url.startswith('ytsearch1:') and entries and entries[0]:
                    info = entries[0]
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
                    return {
                        'title': f"Playlist: {info.get('title', 'Playlist')}",
                        'thumbnail': entries[0].get('thumbnail') if entries and entries[0] else '',
                        'duration': f"{len(entries)} items",
                        'uploader': info.get('uploader', 'Unknown'),
                        'resolutions': ['2160p (4K)', '1080p (Full HD)', '720p (HD)', '480p', 'mp3'],
                        'url': target_url,
                        'is_playlist': True,
                        'playlist_videos': playlist_videos
                    }

            formats = info.get('formats', [])
            resolutions = set()
            for f in formats:
                if f.get('vcodec') != 'none' and f.get('height'):
                    resolutions.add(f.get('height'))
            
            sorted_heights = sorted(list(resolutions), reverse=True)
            available_qualities = []
            for h in sorted_heights:
                if h == 2160: available_qualities.append('2160p (4K)')
                elif h == 1440: available_qualities.append('1440p (2K)')
                elif h == 1080: available_qualities.append('1080p (Full HD)')
                elif h == 720: available_qualities.append('720p (HD)')
                elif h >= 360: available_qualities.append(f'{h}p')
            
            if not any(q.endswith('p') or '(' in q for q in available_qualities):
                available_qualities.extend(['1080p (Full HD)', '720p (HD)', '480p'])
            available_qualities.append('mp3')

            best_audio_codec = None
            max_audio_bitrate = 0
            for f in formats:
                codec = f.get('acodec')
                if codec and codec != 'none':
                    bitrate = f.get('abr') or f.get('tbr') or 0
                    if bitrate > max_audio_bitrate:
                        max_audio_bitrate = int(bitrate)
                        best_audio_codec = codec.split('.')[0]
            
            if not best_audio_codec:
                best_audio_codec = "aac"
                max_audio_bitrate = 128

            recommendation = f" เสียงต้นฉบับเป็น {best_audio_codec.upper()} ({max_audio_bitrate} kbps) แนะนำให้เลือก M4A Original หรือ MP3 320kbps เพื่อความคมชัดดั้งเดิม"

            return {
                'title': custom_title if custom_title else info.get('title'),
                'thumbnail': info.get('thumbnail'),
                'duration': info.get('duration_string', ''),
                'uploader': info.get('uploader', 'Unknown'),
                'resolutions': available_qualities,
                'url': url,
                'audio_codec': best_audio_codec,
                'audio_bitrate': max_audio_bitrate if max_audio_bitrate > 0 else None,
                'audio_recommendation': recommendation
            }
        except Exception as e:
            logging.error(f"Error in process_input for {url}: {e}", exc_info=True)
            return {'error': str(e)}

    # --------------------------------------------------
    # Download Execution
    # --------------------------------------------------
    def start_download(self, params):
        url = params.get('url')
        format_type = params.get('format_type')
        bitrate = params.get('bitrate', '192')
        subtitles = str(params.get('subtitles', 'false')).lower()
        video_container = params.get('video_container', 'mp4')
        embed_metadata = str(params.get('embed_metadata', 'false')).lower()

        if not url:
            return {'error': 'Missing URL parameter.'}

        download_id = str(uuid.uuid4())
        
        threading.Thread(
            target=self._run_download_thread,
            args=(download_id, url, format_type, bitrate, subtitles, video_container, embed_metadata),
            daemon=True
        ).start()

        return {'status': 'started', 'download_id': download_id}

    def cancel_download(self, download_id):
        if download_id:
            self.cancelled_downloads.add(download_id)
            logging.info(f"Cancellation requested for download: {download_id}")
            return {'status': 'cancel_requested'}
        return {'error': 'Missing download_id'}

    def _push_progress(self, download_id, status_data, force=False):
        """Push real-time progress data to AlpineJS via pywebview evaluate_js with rate-limiting (~15 updates/sec / ~65ms)."""
        if not self._window:
            return

        import time
        now = time.time()
        status = status_data.get('status')
        percent = status_data.get('percent', 0)

        if force or status != 'downloading' or percent == 100:
            should_push = True
        else:
            with self._push_lock:
                last_time = self._last_push_time.get(download_id, 0)
                if now - last_time >= 0.065:  # ~15 updates/sec max (~65ms)
                    self._last_push_time[download_id] = now
                    should_push = True
                else:
                    should_push = False

        if should_push:
            try:
                js_code = f"if (window.updateDownloadProgress) window.updateDownloadProgress('{download_id}', {json.dumps(status_data)});"
                self._window.evaluate_js(js_code)
            except Exception as e:
                logging.debug(f"Error evaluating JS for progress: {e}")

    def is_downloading(self):
        """Check if any download thread is currently active."""
        with self._download_lock:
            return len(self.active_downloads) > 0

    def _run_download_thread(self, download_id, url, format_type, bitrate, subtitles, video_container='mp4', embed_metadata='false'):
        with self._download_lock:
            self.active_downloads.add(download_id)
        try:
            save_dir = self.config.get('save_folder')
            os.makedirs(save_dir, exist_ok=True)
            
            urls = [u.strip() for u in url.replace('\n', ',').split(',') if u.strip()]
            
            is_playlist = False
            if len(urls) == 1:
                if not urls[0].startswith("spotify_track:"):
                    ydl_opts_check = {'quiet': True, 'extract_flat': True, 'nocache': True}
                    check_info = extract_info_with_fallback(urls[0], ydl_opts_check)
                    if check_info.get('_type') == 'playlist':
                        is_playlist = True

            def make_progress_hook(d_id):
                def hook(d):
                    if d_id in self.cancelled_downloads:
                        raise Exception("Download cancelled by user")
                    if d['status'] == 'downloading':
                        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                        downloaded = d.get('downloaded_bytes', 0)
                        percent_val = 0
                        if total > 0:
                            percent_val = int(downloaded * 100 / total)
                        
                        percent_str = d.get('_percent_str', '0%').replace('%', '').strip()
                        try: percent_val = int(float(percent_str))
                        except ValueError: pass
                            
                        speed_str = d.get('_speed_str', 'Unknown speed').strip()
                        eta_str = d.get('_eta_str', 'Unknown ETA').strip()
                        size_str = f"{format_bytes(downloaded)} / {format_bytes(total)}" if total > 0 else format_bytes(downloaded)
                        
                        status_data = {
                            'status': 'downloading',
                            'percent': percent_val,
                            'speed': speed_str,
                            'eta': eta_str,
                            'size': size_str
                        }
                        self._push_progress(d_id, status_data)
                    elif d['status'] == 'finished':
                        status_data = {
                            'status': 'processing',
                            'percent': 99,
                            'speed': 'Processing...',
                            'eta': '00:00',
                            'size': 'Merging...'
                        }
                        self._push_progress(d_id, status_data)
                return hook

            _tagged_files = set()

            def make_postprocessor_hook(d_id, override_title=None, override_artist=None, override_cover=None):
                def hook(d):
                    if d_id in self.cancelled_downloads:
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
                'fragment_retries': 10,
                'sleep_interval': 1,
                'max_sleep_interval': 3,
                'sleep_interval_requests': 1,
            }
            
            if is_playlist:
                if subtitles == 'true':
                    ydl_opts.update({
                        'writesubtitles': True, 'writeautomaticsub': True, 'embedsubtitles': True,
                        'postprocessors': [{'key': 'FFmpegEmbedSubtitle'}]
                    })

                if format_type == 'mp3':
                    ydl_opts.update({'format': 'bestaudio/best', 'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': bitrate}]})
                elif format_type == 'm4a':
                    ydl_opts.update({'format': 'bestaudio[ext=m4a]/bestaudio/best', 'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'm4a'}]})
                elif format_type == 'flac':
                    ydl_opts.update({'format': 'bestaudio/best', 'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'flac'}]})
                elif format_type == 'wav':
                    ydl_opts.update({'format': 'bestaudio/best', 'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'wav'}]})
                elif format_type.startswith('mp4_'):
                    height = int(format_type.split('_')[1]) if '_' in format_type else 2160
                    ydl_opts.update({'format': f'bestvideo[height<={height}]+bestaudio/best[height<={height}]/best', 'merge_output_format': video_container})
                else:
                    ydl_opts.update({'format': 'bestvideo+bestaudio/best', 'merge_output_format': video_container})
                    
                download_url_with_fallback(ydl_opts, urls[0])
            else:
                total_batch = len(urls)
                completed_batch = 0
                failed_batch = 0
                for batch_idx, target_url in enumerate(urls):
                    if download_id in self.cancelled_downloads:
                        raise Exception("Download cancelled by user")
                    is_missav = 'missav.' in target_url
                    final_url = target_url
                    custom_title = None
                    override_title = override_artist = override_cover = None

                    if target_url.startswith("spotify_track:"):
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
                        safe_title = re.sub(r'[\\/*?:"<>|]', "", custom_title)[:100].strip()
                        output_template = os.path.join(save_dir, f"{safe_title}.%(ext)s")
                    
                    batch_percent = int((batch_idx / total_batch) * 100)
                    self._push_progress(download_id, {
                        'status': 'downloading',
                        'percent': max(batch_percent, 1),
                        'speed': f'Track {batch_idx + 1}/{total_batch}',
                        'eta': f'{total_batch - batch_idx} remaining',
                        'size': f'Done: {completed_batch} | Failed: {failed_batch}'
                    })

                    ydl_opts = {
                        'outtmpl': output_template,
                        'quiet': True,
                        'nocache': True,
                        'progress_hooks': [make_progress_hook(download_id)],
                        'postprocessor_hooks': [make_postprocessor_hook(download_id, override_title, override_artist, override_cover)],
                        'retries': 10,
                        'fragment_retries': 10,
                        'sleep_interval': 1,
                        'max_sleep_interval': 3,
                        'sleep_interval_requests': 1,
                    }
                    
                    if is_missav:
                        from urllib.parse import urlparse
                        ydl_opts['referer'] = f"https://{urlparse(target_url).netloc}/"

                    if subtitles == 'true':
                        ydl_opts.update({'writesubtitles': True, 'writeautomaticsub': True, 'embedsubtitles': True, 'postprocessors': [{'key': 'FFmpegEmbedSubtitle'}]})

                    if format_type == 'mp3':
                        ydl_opts.update({'format': 'bestaudio/best', 'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': bitrate}]})
                    elif format_type == 'm4a':
                        ydl_opts.update({'format': 'bestaudio[ext=m4a]/bestaudio/best', 'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'm4a'}]})
                    elif format_type == 'flac':
                        ydl_opts.update({'format': 'bestaudio/best', 'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'flac'}]})
                    elif format_type == 'wav':
                        ydl_opts.update({'format': 'bestaudio/best', 'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'wav'}]})
                    elif format_type.startswith('mp4_'):
                        height = int(format_type.split('_')[1]) if '_' in format_type else 2160
                        ydl_opts.update({'format': f'bestvideo[height<={height}]+bestaudio/best[height<={height}]/best', 'merge_output_format': video_container})
                    else:
                        ydl_opts.update({'format': 'bestvideo+bestaudio/best', 'merge_output_format': video_container})

                    try:
                        download_url_with_fallback(ydl_opts, final_url)
                        completed_batch += 1
                    except Exception as b_err:
                        logging.error(f"Error downloading batch item {final_url}: {b_err}")
                        failed_batch += 1

            self._push_progress(download_id, {
                'status': 'finished',
                'percent': 100,
                'speed': 'Done',
                'eta': '00:00',
                'size': 'Complete'
            }, force=True)
        except Exception as e:
            logging.error(f"Download thread error for {download_id}: {e}", exc_info=True)
            self._push_progress(download_id, {
                'status': 'error',
                'percent': 0,
                'speed': 'Error',
                'eta': 'Failed',
                'size': str(e)
            }, force=True)
        finally:
            with self._download_lock:
                self.active_downloads.discard(download_id)
                self.cancelled_downloads.discard(download_id)

    # --------------------------------------------------
    # Engine & App Updater
    # --------------------------------------------------
    def engine_status(self):
        try:
            current_version = yt_dlp.version.__version__
            is_updated = os.path.exists(os.path.join(self.app_path, 'bin', 'yt-dlp-update'))
            latest_version = current_version
            try:
                req = urllib.request.Request("https://pypi.org/pypi/yt-dlp/json", headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=5) as res:
                    pypi_data = json.loads(res.read().decode('utf-8'))
                    latest_version = pypi_data['info']['version']
            except Exception: pass

            update_version = None
            update_path = os.path.join(self.app_path, 'bin', 'yt-dlp-update')
            if os.path.exists(update_path):
                ver_file = os.path.join(update_path, 'yt_dlp', 'version.py')
                if os.path.exists(ver_file):
                    with open(ver_file, 'r', encoding='utf-8') as vf:
                        match = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", vf.read())
                        if match: update_version = match.group(1)

            update_pending_restart = False
            if update_version and latest_version:
                if normalize_version(update_version) == normalize_version(latest_version) and normalize_version(current_version) != normalize_version(latest_version):
                    update_pending_restart = True

            return {
                'current_version': current_version,
                'latest_version': latest_version,
                'is_updated': is_updated,
                'needs_update': normalize_version(current_version) != normalize_version(latest_version),
                'update_pending_restart': update_pending_restart,
                'auto_update': self.auto_update_status
            }
        except Exception as e:
            return {'error': str(e)}

    def revert_engine(self):
        try:
            update_path = os.path.join(self.app_path, 'bin', 'yt-dlp-update')
            if os.path.exists(update_path):
                shutil.rmtree(update_path, ignore_errors=True)
                return {'message': 'ล้างการอัปเดตและคืนค่าเป็นเครื่องยนต์เริ่มต้นเรียบร้อยแล้ว กรุณาเริ่มโปรแกรมใหม่'}
            return {'message': 'คุณกำลังใช้งานเครื่องยนต์เริ่มต้นอยู่แล้ว'}
        except Exception as e:
            return {'error': str(e)}

    def update_engine(self):
        try:
            req = urllib.request.Request("https://pypi.org/pypi/yt-dlp/json", headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as res:
                pypi_data = json.loads(res.read().decode('utf-8'))
            latest_version = pypi_data['info']['version']
            
            whl_url = next((u['url'] for u in pypi_data['urls'] if u['filename'].endswith('.whl')), None)
            if not whl_url: raise Exception("Could not find a valid release package on PyPI.")
                
            temp_file_path = os.path.join(tempfile.gettempdir(), "yt_dlp_update.whl")
            with urllib.request.urlopen(urllib.request.Request(whl_url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=60) as res_dl:
                with open(temp_file_path, 'wb') as out_file: out_file.write(res_dl.read())
                    
            target_dir = os.path.join(self.app_path, 'bin', 'yt-dlp-update')
            os.makedirs(target_dir, exist_ok=True)
                
            with zipfile.ZipFile(temp_file_path, 'r') as zip_ref:
                for file in zip_ref.namelist():
                    if file.startswith('yt_dlp/'): zip_ref.extract(file, target_dir)
                        
            try: os.remove(temp_file_path)
            except Exception: pass
                
            return {'message': f'Engine updated successfully to v{latest_version}. Please restart the application.'}
        except Exception as e:
            return {'error': str(e)}

    def get_app_status(self):
        latest_version = APP_VERSION
        download_url = ""
        release_notes = ""
        needs_update = False
        try:
            req = urllib.request.Request("https://api.github.com/repos/ling-gwdgw2/downloading-mp3-mp4/releases/latest", headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as res:
                data = json.loads(res.read().decode('utf-8'))
                latest_tag = data.get('tag_name', '').strip('v')
                if latest_tag:
                    latest_version = latest_tag
                    release_notes = data.get('body', '')
                    for asset in data.get('assets', []):
                        if asset.get('name', '').endswith('.exe'):
                            download_url = asset.get('browser_download_url', '')
                            break
                    needs_update = normalize_version(APP_VERSION) != normalize_version(latest_version)
        except Exception as e:
            logging.error(f"Failed to check GitHub releases: {e}")
        
        return {
            'current_version': APP_VERSION,
            'latest_version': latest_version,
            'needs_update': needs_update,
            'download_url': download_url,
            'release_notes': release_notes
        }

    def start_app_update_download(self, url):
        if not url: return {'error': 'URL สำหรับอัปเดตว่างเปล่า'}
        if self.app_update_downloading: return {'message': 'กำลังดาวน์โหลดอัปเดตอยู่แล้ว'}
        
        def dl_thread():
            try:
                self.app_update_downloading = True
                self.app_update_status = "downloading"
                self.app_update_progress = 0
                dest_path = os.path.join(tempfile.gettempdir(), "PhoebeDownloaderSetup_update.exe")
                
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=15) as response:
                    total_size = int(response.info().get('Content-Length', 0))
                    downloaded = 0
                    with open(dest_path, 'wb') as f:
                        while True:
                            block = response.read(8192)
                            if not block: break
                            f.write(block)
                            downloaded += len(block)
                            if total_size > 0: self.app_update_progress = int((downloaded / total_size) * 100)
                
                self.downloaded_installer_path = dest_path
                self.app_update_status = "ready"
            except Exception as e:
                self.app_update_status = "error"
                self.app_update_error = str(e)
            finally:
                self.app_update_downloading = False

        threading.Thread(target=dl_thread, daemon=True).start()
        return {'message': 'เริ่มดาวน์โหลดอัปเดตในเบื้องหลังแล้ว'}

    def get_app_update_progress(self):
        return {
            'status': self.app_update_status,
            'progress': self.app_update_progress,
            'error': self.app_update_error
        }

    def trigger_app_update(self):
        if not self.downloaded_installer_path or not os.path.exists(self.downloaded_installer_path):
            return {'error': 'ไม่พบไฟล์ติดตั้งสำหรับอัปเดต'}
        try:
            import subprocess
            import time
            subprocess.Popen([self.downloaded_installer_path], shell=True)
            def exit_soon():
                time.sleep(1)
                os._exit(0)
            threading.Thread(target=exit_soon, daemon=True).start()
            return {'message': 'กำลังเปิดตัวติดตั้ง...'}
        except Exception as e:
            return {'error': str(e)}

    def close_app(self, force_confirm=False):
        """Production-Grade Graceful Shutdown Pipeline (4 Steps)."""
        if self.is_shutting_down:
            return

        # Step 2: Check active downloads state
        if not force_confirm and self.is_downloading():
            with self._download_lock:
                count = len(self.active_downloads)
            return {
                'requires_confirmation': True,
                'active_count': count,
                'message': f"มี {count} รายการกำลังดาวน์โหลดอยู่ คุณแน่ใจหรือไม่ว่าต้องการออกจากโปรแกรม?"
            }

        self.is_shutting_down = True
        logging.info("Initiating Production-Grade Graceful Shutdown Pipeline...")

        # Step 3: Safety Timeout Guard in background thread (3.0s limit)
        def safety_timeout_guard():
            time.sleep(3.0)
            logging.warning("Graceful Shutdown Safety Guard: 3.0s timeout reached. Force exiting process.")
            os._exit(0)

        guard = threading.Thread(target=safety_timeout_guard, daemon=True)
        guard.start()

        # Step 3: Signal active download threads to terminate
        try:
            with self._download_lock:
                for d_id in list(self.active_downloads):
                    self.cancelled_downloads.add(d_id)
            logging.info("Signaled all active download threads to terminate.")
        except Exception as e:
            logging.error(f"Error signaling download threads: {e}")

        # Step 3: Clean up temporary files (.part, .ytdl, .temp)
        try:
            save_dir = self.config.get('save_folder')
            if save_dir and os.path.exists(save_dir):
                for filename in os.listdir(save_dir):
                    if filename.endswith('.part') or filename.endswith('.ytdl') or filename.endswith('.temp'):
                        try: os.remove(os.path.join(save_dir, filename))
                        except Exception: pass
            logging.info("Temp cleanup completed during shutdown.")
        except Exception as e:
            logging.error(f"Error cleaning up temp files during shutdown: {e}")

        # Step 4: Direct process termination without re-triggering FormClosing recursion
        logging.info("Exiting native app process with code 0.")
        os._exit(0)
