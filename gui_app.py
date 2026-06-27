import os
import re
import sys
import threading
import urllib.request
import io
import webbrowser
import socket
import time
from PIL import Image, ImageTk
import customtkinter as ctk

# Determine path for running as EXE vs script
if getattr(sys, 'frozen', False):
    app_path = os.path.dirname(sys.executable)
else:
    app_path = os.path.dirname(os.path.abspath(__file__))

# Dynamic Engine Loading
# Check if an updated version of yt-dlp was downloaded to 'bin/yt-dlp-update'
update_path = os.path.join(app_path, 'bin', 'yt-dlp-update')
if os.path.exists(update_path):
    sys.path.insert(0, update_path)
    print("Dynamically loaded updated yt-dlp engine from: bin/yt-dlp-update")

import yt_dlp


# Configure local FFmpeg path
BIN_FOLDER = os.path.join(app_path, 'bin')
if os.path.exists(os.path.join(BIN_FOLDER, 'ffmpeg.exe')):
    os.environ["PATH"] += os.pathsep + BIN_FOLDER
    print(f"Using local FFmpeg from: {BIN_FOLDER}")

try:
    DOWNLOAD_FOLDER = os.path.join(os.path.expanduser('~'), 'Downloads')
    if not os.path.exists(DOWNLOAD_FOLDER):
        os.makedirs(DOWNLOAD_FOLDER)
except Exception:
    DOWNLOAD_FOLDER = app_path

# Theme configuration
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class DownloaderApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("Universal Video & Audio Downloader")
        self.geometry("850x740")
        self.resizable(False, False)
        
        self.fetched_info = None
        self.fetching = False
        self.downloading = False
        self.updating_engine = False
        self.download_folder = DOWNLOAD_FOLDER
        self.last_progress_update = 0
        
        self.setup_ui()
        
    def setup_ui(self):
        # Header Label
        self.header_label = ctk.CTkLabel(
            self, 
            text="Universal Video & Audio Downloader", 
            font=ctk.CTkFont(size=26, weight="bold")
        )
        self.header_label.pack(pady=(20, 5))
        
        self.subtitle_label = ctk.CTkLabel(
            self,
            text="Supports YouTube, TikTok, Facebook, Instagram, Bilibili, and 1,000+ sites",
            font=ctk.CTkFont(size=13, slant="italic"),
            text_color="#a0a0a0"
        )
        self.subtitle_label.pack(pady=(0, 15))
        
        # URL Input Frame
        self.input_frame = ctk.CTkFrame(self)
        self.input_frame.pack(fill="x", padx=40, pady=5)
        
        self.url_entry = ctk.CTkEntry(
            self.input_frame, 
            placeholder_text="Paste your video/audio link here (YouTube, TikTok, FB, IG, etc.)...",
            height=40,
            font=ctk.CTkFont(size=14)
        )
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(10, 10), pady=10)
        
        self.fetch_btn = ctk.CTkButton(
            self.input_frame, 
            text="Fetch Info", 
            width=120, 
            height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self.start_fetch_info
        )
        self.fetch_btn.pack(side="right", padx=(0, 10), pady=10)

        self.reset_btn = ctk.CTkButton(
            self.input_frame,
            text="Reset",
            width=90,
            height=40,
            fg_color="#dc3545",
            hover_color="#bd2130",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self.reset_app
        )
        self.reset_btn.pack(side="right", padx=(0, 5), pady=10)

        # Save Path Frame
        self.path_frame = ctk.CTkFrame(self)
        self.path_frame.pack(fill="x", padx=40, pady=5)
        
        self.path_label_title = ctk.CTkLabel(
            self.path_frame,
            text="Save folder:",
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.path_label_title.pack(side="left", padx=(15, 10), pady=10)
        
        self.path_entry = ctk.CTkEntry(
            self.path_frame,
            height=30,
            font=ctk.CTkFont(size=12)
        )
        self.path_entry.pack(side="left", fill="x", expand=True, padx=5, pady=10)
        self.path_entry.insert(0, self.download_folder)
        self.path_entry.configure(state="readonly")
        
        self.browse_btn = ctk.CTkButton(
            self.path_frame,
            text="Browse...",
            width=90,
            height=30,
            command=self.browse_folder
        )
        self.browse_btn.pack(side="right", padx=(10, 15), pady=10)

        
        # Info & Details Frame (Holds Thumbnail and Video Metadata)
        self.info_frame = ctk.CTkFrame(self)
        self.info_frame.pack(fill="both", expand=True, padx=40, pady=10)
        
        # Grid layout for Info Frame
        self.info_frame.grid_columnconfigure(0, weight=1) # Thumbnail
        self.info_frame.grid_columnconfigure(1, weight=1) # Metadata
        self.info_frame.grid_rowconfigure(0, weight=1)
        
        # Left side: Thumbnail Placeholder
        self.thumb_label = ctk.CTkLabel(
            self.info_frame, 
            text="Thumbnail preview will appear here",
            width=320,
            height=180,
            fg_color="#2b2b2b",
            corner_radius=8
        )
        self.thumb_label.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        
        # Right side: Metadata fields
        self.meta_frame = ctk.CTkFrame(self.info_frame, fg_color="transparent")
        self.meta_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        
        self.title_label = ctk.CTkLabel(
            self.meta_frame, 
            text="Title: -", 
            anchor="w", 
            justify="left",
            font=ctk.CTkFont(size=14, weight="bold"),
            wraplength=380
        )
        self.title_label.pack(fill="x", pady=(0, 10))
        
        self.uploader_label = ctk.CTkLabel(
            self.meta_frame, 
            text="Uploader: -", 
            anchor="w",
            font=ctk.CTkFont(size=13)
        )
        self.uploader_label.pack(fill="x", pady=5)
        
        self.duration_label = ctk.CTkLabel(
            self.meta_frame, 
            text="Duration: -", 
            anchor="w",
            font=ctk.CTkFont(size=13)
        )
        self.duration_label.pack(fill="x", pady=5)
        
        # Controls Frame (Format Dropdown & Download Button)
        self.controls_frame = ctk.CTkFrame(self)
        self.controls_frame.pack(fill="x", padx=40, pady=10)
        
        self.quality_label = ctk.CTkLabel(
            self.controls_frame, 
            text="Select Quality:", 
            font=ctk.CTkFont(size=13)
        )
        self.quality_label.pack(side="left", padx=(20, 10), pady=15)
        
        self.quality_menu = ctk.CTkOptionMenu(
            self.controls_frame,
            values=["Please fetch info first"],
            width=180,
            state="disabled",
            command=self.on_quality_changed
        )
        self.quality_menu.pack(side="left", padx=10, pady=15)
        
        # Audio Quality (Bitrate) - Hidden by default, packed dynamically
        self.bitrate_label = ctk.CTkLabel(
            self.controls_frame,
            text="Audio Bitrate:",
            font=ctk.CTkFont(size=13)
        )
        
        self.bitrate_menu = ctk.CTkOptionMenu(
            self.controls_frame,
            values=["128 kbps", "192 kbps (Recommended)", "320 kbps (Studio)"],
            width=170
        )
        self.bitrate_menu.set("192 kbps (Recommended)")
        
        self.download_btn = ctk.CTkButton(
            self.controls_frame, 
            text="Download", 
            width=120,
            state="disabled",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self.start_download
        )
        self.download_btn.pack(side="right", padx=(0, 20), pady=15)
        
        # Progress & Status Frame
        self.progress_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.progress_frame.pack(fill="x", padx=40, pady=(10, 5))
        
        self.status_label = ctk.CTkLabel(
            self.progress_frame, 
            text="Status: Idle", 
            anchor="w",
            font=ctk.CTkFont(size=13, slant="italic")
        )
        self.status_label.pack(fill="x", pady=2)
        
        self.progress_bar = ctk.CTkProgressBar(self.progress_frame)
        self.progress_bar.pack(fill="x", pady=8)
        self.progress_bar.set(0)
        
        self.detail_progress_label = ctk.CTkLabel(
            self.progress_frame, 
            text="Speed: -- | ETA: -- | Progress: 0%", 
            anchor="w",
            font=ctk.CTkFont(size=12)
        )
        self.detail_progress_label.pack(fill="x", pady=2)
        
        # Open Folder Button
        self.open_folder_btn = ctk.CTkButton(
            self.progress_frame,
            text="Open Downloads Folder",
            width=180,
            fg_color="#28a745",
            hover_color="#218838",
            command=self.open_downloads_dir
        )
        # Hidden by default
        self.open_folder_btn.pack_forget()

        # Footer Frame (Engine Status & Update)
        self.footer_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.footer_frame.pack(fill="x", padx=40, pady=(5, 10))
        
        try:
            import yt_dlp.version
            yt_dlp_version = yt_dlp.version.__version__
        except Exception:
            yt_dlp_version = getattr(yt_dlp, '__version__', 'Unknown')
            
        self.version_label = ctk.CTkLabel(
            self.footer_frame,
            text=f"Engine core: yt-dlp v{yt_dlp_version}",
            font=ctk.CTkFont(size=11),
            text_color="#888888"
        )
        self.version_label.pack(side="left", pady=5)
        
        self.update_btn = ctk.CTkButton(
            self.footer_frame,
            text="Update Engine",
            width=110,
            height=24,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.start_update_engine
        )
        self.update_btn.pack(side="right", pady=5)

        # End Credit
        self.credit_label = ctk.CTkLabel(
            self,
            text="Copyright © 2026 LING Rube",
            font=ctk.CTkFont(size=11),
            text_color="#666666"
        )
        self.credit_label.pack(side="bottom", pady=(0, 10))



    # --- Fetch Video Info Logic ---
    
    def start_fetch_info(self):
        url = self.url_entry.get().strip()
        if not url:
            self.set_status("Error: Please paste a URL first.")
            return
            
        if self.fetching:
            self.set_status("Please wait, already fetching video info.")
            return
            
        if self.downloading:
            self.set_status("Please wait, a download is currently in progress.")
            return

        # Clear previous metadata
        self.fetched_info = None
            
        self.fetching = True
        self.fetch_btn.configure(state="disabled", text="Fetching...")
        self.download_btn.configure(state="disabled")
        self.quality_menu.configure(state="disabled")
        self.set_status("Fetching video information from URL...")
        
        # Reset UI placeholders
        self.title_label.configure(text="Title: Fetching...")
        self.uploader_label.configure(text="Uploader: -")
        self.duration_label.configure(text="Duration: -")
        self.thumb_label.configure(image=None, text="Loading preview...")
        self.open_folder_btn.pack_forget()
        self.progress_bar.set(0)
        self.detail_progress_label.configure(text="Speed: -- | ETA: -- | Progress: 0%")
        
        # Start fetch thread
        threading.Thread(target=self.fetch_info_thread, args=(url,), daemon=True).start()

    def fetch_info_thread(self, url):
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'socket_timeout': 10,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Connection': 'close',
                }
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                # Fetch thumbnail
                thumbnail_pil = None
                thumb_url = info.get('thumbnail')
                if thumb_url:
                    try:
                        req = urllib.request.Request(
                            thumb_url, 
                            headers={
                                'User-Agent': 'Mozilla/5.0',
                                'Connection': 'close'
                            }
                        )
                        with urllib.request.urlopen(req, timeout=10) as res:
                            raw_data = res.read()
                        thumbnail_pil = Image.open(io.BytesIO(raw_data))
                    except Exception as img_err:
                        print(f"Error loading thumbnail: {img_err}")
                
                # Available qualities
                formats = info.get('formats', [])
                resolutions = set()
                for f in formats:
                    if f.get('vcodec') != 'none' and f.get('height'):
                        resolutions.add(f.get('height'))
                
                available_qualities = []
                if 2160 in resolutions: available_qualities.append('2160p (MP4)')
                if 1080 in resolutions: available_qualities.append('1080p (MP4)')
                if 720 in resolutions: available_qualities.append('720p (MP4)')
                available_qualities.append('Default/Auto (MP4)')
                available_qualities.append('MP3 (Audio)')
                
                self.fetched_info = {
                    'title': info.get('title', 'Unknown Title'),
                    'uploader': info.get('uploader', 'Unknown'),
                    'duration': info.get('duration_string', 'Unknown'),
                    'thumbnail_pil': thumbnail_pil,
                    'url': url,
                    'resolutions': available_qualities
                }
                
                self.after(0, self.on_fetch_success)
                
        except Exception as e:
            self.after(0, lambda: self.on_fetch_failed(str(e)))


    def on_fetch_success(self):
        self.fetching = False
        self.fetch_btn.configure(state="normal", text="Fetch Info")
        
        info = self.fetched_info
        self.title_label.configure(text=f"Title: {info['title']}")
        self.uploader_label.configure(text=f"Uploader: {info['uploader']}")
        self.duration_label.configure(text=f"Duration: {info['duration']}")
        
        if info['thumbnail_pil']:
            try:
                img = info['thumbnail_pil'].resize((320, 180), Image.Resampling.LANCZOS)
                thumbnail_img = ctk.CTkImage(light_image=img, dark_image=img, size=(320, 180))
                self.thumb_label.configure(image=thumbnail_img, text="")
            except Exception as img_err:
                print(f"Error creating CTkImage: {img_err}")
                self.thumb_label.configure(image=None, text="[Error Preview]")
        else:
            self.thumb_label.configure(image=None, text="[No Thumbnail]")
            
        self.quality_menu.configure(values=info['resolutions'], state="normal")
        self.quality_menu.set(info['resolutions'][0])
        self.download_btn.configure(state="normal")
        
        self.set_status("Metadata loaded successfully. Ready to download.")

    def on_fetch_failed(self, err_msg):
        self.fetching = False
        self.fetch_btn.configure(state="normal", text="Fetch Info")
        self.title_label.configure(text="Title: Error loading info")
        self.thumb_label.configure(image=None, text="Error loading preview")
        self.set_status(f"Failed to fetch metadata: {err_msg}")

    # --- Video/Audio Download Logic ---

    def start_download(self):
        if not self.fetched_info or self.downloading or self.fetching:
            return
            
        self.downloading = True
        self.download_btn.configure(state="disabled", text="Downloading...")
        self.fetch_btn.configure(state="disabled")
        self.quality_menu.configure(state="disabled")
        self.open_folder_btn.pack_forget()
        self.set_status("Starting download...")
        
        quality = self.quality_menu.get()
        threading.Thread(target=self.download_thread, args=(quality,), daemon=True).start()

    def download_thread(self, quality):
        try:
            info = self.fetched_info
            url = info['url']
            
            output_template = os.path.join(self.download_folder, '%(title)s.%(ext)s')
            
            # Setup yt-dlp options
            ydl_opts = {
                'outtmpl': output_template,
                'quiet': True,
                'progress_hooks': [self.yt_dlp_progress_hook],
                'socket_timeout': 15,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Connection': 'close',
                }
            }

            # Determine format parameters
            if 'MP3 (Audio)' in quality:
                bitrate_text = self.bitrate_menu.get()
                bitrate_val = "192"  # default fallback
                match = re.search(r'\d+', bitrate_text)
                if match:
                    bitrate_val = match.group(0)
                    
                ydl_opts.update({
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': bitrate_val,
                    }],
                })
            elif '2160p' in quality:
                ydl_opts.update({
                    'format': 'bestvideo[height=2160]+bestaudio/best[height=2160]',
                    'merge_output_format': 'mp4'
                })
            elif '1080p' in quality:
                ydl_opts.update({
                    'format': 'bestvideo[height=1080]+bestaudio/best[height=1080]',
                    'merge_output_format': 'mp4'
                })
            elif '720p' in quality:
                ydl_opts.update({
                    'format': 'bestvideo[height=720]+bestaudio/best[height=720]/best[height<=720]',
                    'merge_output_format': 'mp4'
                })
            else: # Default/Auto (MP4)
                ydl_opts.update({
                    'format': 'best[ext=mp4]/best',
                })

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
                
            self.after(0, self.on_download_success)
            
        except Exception as e:
            self.after(0, lambda: self.on_download_failed(str(e)))



    def yt_dlp_progress_hook(self, d):
        if d['status'] == 'downloading':
            current_time = time.time()
            # Throttle UI updates to once every 0.1 seconds to prevent flooding Tkinter event queue
            if current_time - self.last_progress_update < 0.1:
                return
            self.last_progress_update = current_time
            
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            
            percent_val = 0.0
            if total > 0:
                percent_val = downloaded / total
                
            percent_str = d.get('_percent_str', '').strip()
            speed_str = d.get('_speed_str', 'Unknown speed').strip()
            eta_str = d.get('_eta_str', 'Unknown ETA').strip()
            
            self.after(0, lambda: self.update_ui_progress(percent_val, percent_str, speed_str, eta_str))
        elif d['status'] == 'finished':
            self.after(0, lambda: self.set_status("Finishing and post-processing download..."))

    def update_ui_progress(self, percent, percent_str, speed, eta):
        self.progress_bar.set(percent)
        self.detail_progress_label.configure(
            text=f"Speed: {speed} | ETA: {eta} | Progress: {percent_str}"
        )
        self.set_status(f"Downloading... ({percent_str})")

    def on_download_success(self):
        self.downloading = False
        self.download_btn.configure(state="normal", text="Download")
        self.fetch_btn.configure(state="normal")
        self.quality_menu.configure(state="normal")
        
        self.progress_bar.set(1.0)
        self.detail_progress_label.configure(text="Progress: 100% | Completed!")
        self.set_status("Download completed successfully!")
        
        # Show Open Folder Button
        self.open_folder_btn.pack(side="top", pady=10)
        
        # Auto-open directory for user convenience
        self.open_downloads_dir()

    def on_download_failed(self, err_msg):
        self.downloading = False
        self.download_btn.configure(state="normal", text="Download")
        self.fetch_btn.configure(state="normal")
        self.quality_menu.configure(state="normal")
        
        self.progress_bar.set(0)
        self.set_status(f"Download failed: {err_msg}")

    # --- UI Utility Methods ---
    
    def set_status(self, text):
        self.status_label.configure(text=f"Status: {text}")

    def browse_folder(self):
        from tkinter import filedialog
        selected_dir = filedialog.askdirectory(initialdir=self.download_folder)
        if selected_dir:
            self.download_folder = selected_dir
            self.path_entry.configure(state="normal")
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, self.download_folder)
            self.path_entry.configure(state="readonly")

    def on_quality_changed(self, value):
        if "MP3 (Audio)" in value:
            self.bitrate_label.pack(side="left", padx=(15, 5), pady=15)
            self.bitrate_menu.pack(side="left", padx=5, pady=15)
        else:
            self.bitrate_label.pack_forget()
            self.bitrate_menu.pack_forget()

    def reset_app(self):
        self.fetching = False
        self.downloading = False
        self.fetched_info = None
        
        # Clear URL text entry
        self.url_entry.delete(0, "end")
        
        # Reset UI Labels
        self.title_label.configure(text="Title: -")
        self.uploader_label.configure(text="Uploader: -")
        self.duration_label.configure(text="Duration: -")
        self.thumb_label.configure(image=None, text="Thumbnail preview will appear here")
        
        # Reset Qualities Dropdown
        self.quality_menu.configure(values=["Please fetch info first"], state="disabled")
        self.quality_menu.set("Please fetch info first")
        self.download_btn.configure(state="disabled", text="Download")
        self.fetch_btn.configure(state="normal", text="Fetch Info")
        
        # Hide quality dependent components
        self.bitrate_label.pack_forget()
        self.bitrate_menu.pack_forget()
        self.open_folder_btn.pack_forget()
        
        # Reset Progress indicators
        self.progress_bar.set(0)
        self.detail_progress_label.configure(text="Speed: -- | ETA: -- | Progress: 0%")
        
        self.set_status("Idle (Reset complete)")

    def open_downloads_dir(self):
        def open_dir():
            try:
                if os.path.exists(self.download_folder):
                    os.startfile(self.download_folder)
            except Exception as e:
                print(f"Error opening directory: {e}")
        threading.Thread(target=open_dir, daemon=True).start()


    def start_update_engine(self):
        if self.updating_engine or self.downloading:
            return
            
        self.updating_engine = True
        self.update_btn.configure(state="disabled", text="Updating...")
        self.set_status("Checking for engine updates...")
        
        threading.Thread(target=self.update_engine_thread, daemon=True).start()

    def update_engine_thread(self):
        import json
        import tempfile
        import zipfile
        from tkinter import messagebox
        
        try:
            # 1. Get current version
            try:
                import yt_dlp.version
                current_version = yt_dlp.version.__version__
            except Exception:
                current_version = getattr(yt_dlp, '__version__', '0.0.0')
                
            # 2. Fetch PyPI data
            req = urllib.request.Request("https://pypi.org/pypi/yt-dlp/json", headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as res:
                pypi_data = json.loads(res.read().decode('utf-8'))
                
            latest_version = pypi_data['info']['version']
            
            # Compare versions
            if latest_version == current_version:
                self.after(0, lambda: self.set_status("Engine is already up to date."))
                self.after(0, lambda: self.update_btn.configure(state="normal", text="Update Engine"))
                self.updating_engine = False
                self.after(0, lambda: messagebox.showinfo("Up to Date", "Your downloader engine is already up to date!"))
                return
                
            # 3. Find download url of the wheel file
            urls = pypi_data['urls']
            whl_url = None
            for url_info in urls:
                if url_info['filename'].endswith('.whl'):
                    whl_url = url_info['url']
                    break
            
            if not whl_url:
                for url_info in urls:
                    if url_info['filename'].endswith('.zip') or url_info['filename'].endswith('.tar.gz'):
                        whl_url = url_info['url']
                        break
                        
            if not whl_url:
                raise Exception("Could not find a valid release package on PyPI.")
                
            # 4. Download package
            self.after(0, lambda: self.set_status(f"Downloading yt-dlp v{latest_version} update..."))
            temp_dir = tempfile.gettempdir()
            temp_file_path = os.path.join(temp_dir, "yt_dlp_update.whl")
            
            req_dl = urllib.request.Request(whl_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req_dl, timeout=60) as response_dl:
                with open(temp_file_path, 'wb') as out_file:
                    out_file.write(response_dl.read())
                    
            # 5. Extract yt_dlp package
            self.after(0, lambda: self.set_status("Extracting engine components..."))
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
                
            # Done!
            self.after(0, lambda: self.set_status(f"Engine updated to v{latest_version}. Restart required."))
            self.after(0, lambda: self.update_btn.configure(state="disabled", text="Restart Required"))
            self.updating_engine = False
            
            self.after(0, lambda: messagebox.showinfo(
                "Update Complete", 
                f"Downloader engine updated successfully to v{latest_version}!\n\nPlease restart the application to apply the changes."
            ))
            
        except Exception as e:
            err_msg = str(e)
            self.after(0, lambda: self.set_status(f"Update failed: {err_msg}"))
            self.after(0, lambda: self.update_btn.configure(state="normal", text="Update Engine"))
            self.updating_engine = False
            self.after(0, lambda: messagebox.showerror("Update Error", f"An error occurred while updating the engine:\n\n{err_msg}"))



if __name__ == "__main__":
    app = DownloaderApp()
    app.mainloop()
