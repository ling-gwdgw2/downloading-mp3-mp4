# Phoebe Downloader (v2.3.4) — Technical Architecture & System Report

## 1. Executive Summary

**Phoebe Downloader** is a production-grade, multi-platform media downloading and audio/video processing desktop application. Built with Python 3.11+, `pywebview` (native Windows Forms / WebView2 wrapper), `yt-dlp`, and `FFmpeg`, it delivers a responsive glassmorphic UI powered by Alpine.js and Tailwind CSS without requiring heavy web runtimes like Electron or Chromium binaries.

<img width="1230" height="953" alt="Screenshot 2026-07-23 210407" src="https://github.com/user-attachments/assets/61714d2c-f0b5-49fd-9463-c1bd6cb8d7ed" />

---

## 2. High-Level Architecture Overview

The system follows a decoupled, 3-tier desktop architecture:

```mermaid
graph TD
    subgraph Frontend Layer [Frontend UI - HTML5 / Alpine.js / Tailwind CSS]
        UI[User Interface & Glassmorphic View]
        Alpine[Alpine.js State Manager]
        Synth[Web Audio API Synthesizer]
    end

    subgraph Native Bridge Layer [pywebview JS API Bridge]
        IPC[window.pywebview.api]
        EvalJS[evaluate_js Throttled Progress Push]
    end

    subgraph Backend Engine Layer [Python Backend - PyWebViewAPI]
        API[pywebview_api.py Controller]
        DLThread[Multi-Threaded Download Pool]
        Analyzer[Audio/Video Stream Analyzer]
        PostProc[FFmpeg & Mutagen Tagging]
        Updater[Dynamic Engine Hot-Swapper]
        Shutdown[4-Step Graceful Shutdown Guard]
    end

    UI --> Alpine
    Alpine <-->|Promises| IPC
    IPC <--> API
    API --> DLThread
    DLThread --> Analyzer
    Analyzer --> PostProc
    API --> Shutdown
    API --> Updater
    API -.->|IPC Updates ~15fps| EvalJS
    EvalJS -.-> Alpine
```

---

## 3. Core Systems & Subsystems

### 3.1. Production-Grade Graceful Shutdown Pipeline (4-Step Guard)
To prevent data corruption, zombie background processes, and `.NET` `System.InsufficientExecutionStackException` recursion bugs, the application enforces a strict 4-step shutdown architecture:

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Titlebar as Titlebar [X] / Alt+F4 / OS Signal
    participant AppPy as app.py (FormClosing)
    participant UI as Alpine.js Modal
    participant API as PyWebViewAPI Engine
    participant OS as System OS Process

    User->>Titlebar: Request Close App
    Titlebar->>AppPy: Trigger window.events.closing
    AppPy->>API: Check is_downloading()
    alt Active Downloads Present
        API-->>AppPy: Returns True (Active Jobs > 0)
        AppPy->>UI: Invoke window.onNativeWindowClosing()
        AppPy-->>Titlebar: Return False (Pause OS Close)
        UI->>User: Display Glassmorphic Warning Modal
        User->>UI: Confirm "Force Exit"
        UI->>API: close_app(force_confirm=True)
    else No Active Downloads
        AppPy->>API: close_app(force_confirm=True)
    end
    API->>API: Set is_shutting_down = True
    API->>API: Spawn 3.0s Safety Timeout Guard Thread
    API->>API: Signal threads (cancelled_downloads.add(id))
    API->>API: Clean up temp files (.part, .ytdl, .temp)
    API->>OS: Direct os._exit(0)
```

1. **Step 1: Event Interception:** Intercepts native Windows `FormClosing`, `Alt+F4`, and UI events cleanly.
2. **Step 2: State Verification & Confirmation:** Queries thread-safe download counters (`is_downloading()`). If jobs are active, pops a non-native glassmorphic modal while keeping the app responsive.
3. **Step 3: Cleanup & Signal:** Signals thread cancellation via `cancelled_downloads` set, deletes orphaned `.part`/`.ytdl` files, and runs a **3.0-second Safety Timeout Guard** to force exit if thread joins deadlock.
4. **Step 4: Non-Recursive Native Exit:** Terminates the process using `os._exit(0)` cleanly without triggering WinForms event loops.

---

### 3.2. Adaptive High-Resolution Format Extraction (4K / 2K / 1080p / Audio)
- **Unconstrained DASH Selector:** Utilizes `'bestvideo+bestaudio/best'` format selection strings. Removing legacy Android `player_client` restrictions unlocks YouTube's 39+ adaptive DASH video and audio streams.
- **Dynamic Resolution Resolution Parser:** Detects and parses streams up to **2160p (4K)**, **1440p (2K)**, **1080p (Full HD)**, **720p**, and **480p**.

---

### 3.3. Audio Source Analyzer & Transcoding Engine
- **Source Inspection:** Pre-analyzes source audio codecs (Opus, AAC, MP3, Vorbis) and bitrates.
- **Transcoding Options:** Supports high-quality 320kbps MP3 encoding, M4A container extraction, and Lossless FLAC/WAV conversion via `FFmpeg`.
- **ID3 & Metadata Embedding:** Uses `mutagen` to inject title, artist, album art cover, and track metadata into downloaded audio files.

---

### 3.4. Anti-Blocking & Bot Evasion System
- **Browser Impersonation:** Employs `curl_cffi` to mimic Chrome/Safari TLS fingerprints.
- **Request Normalization:** Implements user-agent rotation, custom header sets, PO-token handling, and exponential backoff retry algorithms to avoid YouTube IP rate-limiting.

---

### 3.5. Dynamic Engine Updater (Bypassing PyInstaller `FrozenImporter`)
- **Hot-Swapping Binary Engine:** Checks PyPI for the latest `yt-dlp` version. Downloads new engine updates to `bin/yt-dlp-update`.
- **Importer Bypassing:** Dynamically manipulates `sys.meta_path` to bypass PyInstaller's static `FrozenImporter`, allowing seamless engine upgrades without reinstalling the application `.exe`.

---

### 3.6. IPC Throttling & Progress Rate-Limiter
- **Thread-Safe Rate Limiting:** Limits UI progress updates (`_push_progress`) via `_push_lock` and timestamps to ~15 updates/second (~65ms interval).
- **Immediate Terminal Updates:** Forces immediate evaluation (`force=True`) on critical states (`finished`, `error`, `cancelled`) to guarantee zero UI latency on completion.

---

### 3.7. Packaging & Deployment Subsystem
- **PyInstaller Bundle:** Packaging script (`build_exe.py`) compiles the app into a single standalone executable (`dist/YouTubeDownloader.exe`) with bundled `FFmpeg` binaries and `templates/static` assets.
- **Inno Setup Script (`setup.iss` v2.3.0):** Multi-language Windows installer supporting English, Thai, and Lao. Enforces 64-bit Windows 10+ environments and installs cleanly into `{localappdata}\Programs\Phoebe Downloader`.

---

## 4. Technology Stack Summary

| Layer | Technology / Library | Purpose |
| :--- | :--- | :--- |
| **GUI Wrapper** | `pywebview` 5.x (WebView2 / WinForms) | Lightweight native desktop window wrapper |
| **Frontend Framework** | Alpine.js 3.x + Tailwind CSS | Reactive UI state management & glassmorphic styling |
| **Backend Core** | Python 3.11+ | Application logic, threading, and system APIs |
| **Extractor Engine** | `yt-dlp` | Video/audio stream extraction & downloading |
| **Media Converter** | `FFmpeg` | Video/audio merging, format conversion & normalization |
| **Metadata Processor** | `mutagen` | ID3, MP4, FLAC audio metadata & cover art tagging |
| **Network Client** | `curl_cffi` | TLS fingerprint impersonation for anti-bot evasion |
| **Installer** | Inno Setup 6.x (`setup.iss`) | Production Windows installer packaging |

---

## 5. File & Directory Map

```
youtube mp3 mp4/
├── app.py                      # Main entry point & PyWebView window initialization
├── pywebview_api.py            # Backend Native API Controller & Processing Engine
├── build_exe.py                # PyInstaller build automation script
├── setup.iss                   # Inno Setup 6 installer specification script (v2.3.0)
├── templates/
│   ├── index.html              # Main Alpine.js UI layout & controllers
│   ├── setup.html              # FFmpeg initial setup wizard interface
│   └── static/                 # Embedded asset directory (phoebe0.png, phoebe1.png, etc.)
└── bin/                        # Binary executables directory (ffmpeg.exe, ffprobe.exe)
```
