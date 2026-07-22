# Workspace Customizations & Agent Rules

## Versioning Policy Rule
Every time changes or bugfixes/optimizations are made to this project:
1. Increment the patch version number (e.g., `2.3.0` -> `2.3.1` -> `2.3.2` up to `2.3.10`).
2. When the patch version reaches `10` (e.g., `2.3.10`), bump the minor version and reset the patch to `0` (e.g. `2.4.0`).
3. Always update the version across all core files:
   - [pywebview_api.py](file:///c:/Users/vivo9/Desktop/youtube%20mp3%20mp4/pywebview_api.py) (`APP_VERSION`)
   - [templates/index.html](file:///c:/Users/vivo9/Desktop/youtube%20mp3%20mp4/templates/index.html) (`appVersion`, `latestAppVersion`)
   - [setup.iss](file:///c:/Users/vivo9/Desktop/youtube%20mp3%20mp4/setup.iss) (`MyAppVersion`)
   - [README.md](file:///c:/Users/vivo9/Desktop/youtube%20mp3%20mp4/README.md)
4. Rebuild `YouTubeDownloader.exe` via `build_exe.py` and commit/push changes to GitHub.
