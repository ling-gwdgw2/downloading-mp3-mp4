# 🍎🐧 แผนสถาปัตยกรรมและคู่มือการพอร์ตระบบสำหรับ macOS และ Linux

เอกสารฉบับนี้สรุปแนวทางการปรับแต่งโค้ดเบื้องหลังและการสร้างตัวคอมไพล์แอปพลิเคชันดาวน์โหลดวิดีโอ/ไฟล์เสียง (Python Flask + yt-dlp) สำหรับระบบปฏิบัติการ **macOS** และ **Linux** เพื่อให้ตัวแอปพลิเคชันสามารถทำงานข้ามแพลตฟอร์ม (Cross-Platform) ได้อย่างสมบูรณ์แบบ

---

## 🛠️ 1. การปรับแต่งโค้ดฝั่งหลังบ้าน (Cross-Platform Code Optimizations)

เพื่อให้แอปพลิเคชันในไฟล์ **[app.py](file:///c:/Users/vivo9/Desktop/youtube%20mp3%20mp4/app.py)** สามารถทำงานได้บน macOS และ Linux โดยไม่เกิดเออร์เรอร์ ต้องปรับแก้โค้ดระบบตรวจจับดังนี้:

### A. ตรวจหาโฟลเดอร์ Downloads อัตโนมัติในแต่ละ OS
บน Windows เราดึงผ่าน Registry แต่สำหรับ macOS และ Linux เราต้องดึงพาธตามมาตรฐานระบบ:
```python
import platform
import os

def get_default_downloads_path():
    sys_name = platform.system()
    if sys_name == 'Windows':
        try:
            import winreg
            sub_key = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders'
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub_key) as key:
                return os.path.normpath(winreg.QueryValueEx(key, '{374DE290-123F-4565-9164-39C4925E467B}')[0])
        except Exception:
            return os.path.normpath(os.path.join(os.path.expanduser('~'), 'Downloads'))
            
    elif sys_name == 'Darwin':  # macOS
        # คืนค่าโฟลเดอร์ดาวน์โหลดตั้งต้นของ Mac User
        return os.path.expanduser('~/Downloads')
        
    else:  # Linux (Ubuntu / Fedora / Arch)
        # ตรวจหา XDG User Directory Config ถ้ามี หรือใช้ค่าตั้งต้น
        xdg_config = os.path.expanduser('~/.config/user-dirs.dirs')
        if os.path.exists(xdg_config):
            try:
                with open(xdg_config, 'r') as f:
                    for line in f:
                        if line.startswith('XDG_DOWNLOAD_DIR='):
                            path = line.split('=')[1].strip().strip('"').replace('$HOME', os.path.expanduser('~'))
                            return os.path.normpath(path)
            except Exception:
                pass
        return os.path.expanduser('~/Downloads')
```

### B. การปรับการตรวจหา FFmpeg Executable
บน Linux และ macOS ระบบปฏิบัติการไม่ต้องการนามสกุลไฟล์ `.exe` และปกติจะเรียกใช้ผ่าน Global Environment PATH:
```python
def check_ffmpeg_path():
    sys_name = platform.system()
    # หากรันบน Linux/Mac มักมี FFmpeg ติดตั้งในระบบอยู่แล้วใน /usr/bin หรือ /opt/homebrew/bin
    ffmpeg_cmd = 'ffmpeg' if sys_name != 'Windows' else 'ffmpeg.exe'
    
    # ใช้ shutil.which ตรวจหาคำสั่งในเครื่องผู้ใช้โดยตรง
    import shutil
    if shutil.which(ffmpeg_cmd):
        return True
    
    # ค่อยตรวจสอบจากโฟลเดอร์ bin/ ของโปรเจกต์
    local_bin = os.path.join(app_path, 'bin', ffmpeg_cmd)
    return os.path.exists(local_bin)
```

---

## 🍏 2. แผนการพอร์ตสำหรับ macOS (Apple Silicon & Intel)

### A. การเตรียมเครื่องมือของระบบ
1. ติดตั้ง **Homebrew** (ตัวจัดการแพ็กเกจของ Mac):
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```
2. ติดตั้ง **FFmpeg** ลงเครื่องผ่าน Homebrew:
   ```bash
   brew install ffmpeg
   ```

### B. การคอมไพล์เป็นแอปพลิเคชัน Mac (`.app`)
ใช้ PyInstaller บน macOS ในการบีบอัดหน้าเว็บและสคริปต์ให้รันโดยตรง:
```bash
# ติดตั้ง PyInstaller บน Mac
pip install pyinstaller

# คอมไพล์เป็น Mac Bundle Package (.app)
pyinstaller --noconsole --name="YouTubeDownloader" \
  --add-data "templates:templates" \
  --add-data "static:static" \
  app.py
```
*ระบบจะสร้างไฟล์แอปชื่อ **`YouTubeDownloader.app`** ภายในโฟลเดอร์ `dist/` ซึ่งผู้ใช้ macOS สามารถดับเบิ้ลคลิกเพื่อเริ่มต้นรันเครื่องแม่ข่ายโลคอลและแสดงหน้าต่างเบราว์เซอร์ได้ทันที*

### C. การทำไฟล์ติดตั้งดิสก์อิมเมจ (`.dmg`)
เพื่อสร้างไฟล์แจกจ่ายสไตล์พรีเมียม ให้คอมไพล์ `.app` ให้อยู่ในรูป `.dmg` ติดตั้งง่าย:
1. ติดตั้งไลบรารีช่วยทำ DMG: `npm install -g create-dmg`
2. สร้างไฟล์ DMG:
   ```bash
   create-dmg dist/YouTubeDownloader.app dist/
   ```
   ผู้ใช้จะได้รับไฟล์ติดตั้งที่ลากแอปพลิเคชันลงโฟลเดอร์ Applications ของ Mac ได้ทันที

---

## 🐧 3. แผนการพอร์ตสำหรับ Linux (Ubuntu, Debian, Fedora)

### A. การเตรียมเครื่องมือของระบบ
1. ติดตั้ง **FFmpeg** และเครื่องมือจำเป็นผ่าน Terminal:
   ```bash
   # สำหรับระบบ Debian/Ubuntu
   sudo apt update
   sudo apt install ffmpeg python3-pip python3-venv -y
   
   # สำหรับระบบ Fedora/RHEL
   sudo dnf install ffmpeg python3-pip -y
   ```

### B. การคอมไพล์เป็นไฟล์ Binary เดี่ยว (ELF Format)
คอมไพล์โค้ดให้อยู่ในรูปไฟล์ Binary รันง่ายบนเครื่องเซิร์ฟเวอร์หรือเดสก์ท็อปลินุกซ์:
```bash
# รันคอมไพล์บนระบบลินุกซ์
pyinstaller --noconsole --name="youtube-downloader-linux" \
  --add-data "templates:templates" \
  --add-data "static:static" \
  app.py
```
ผลลัพธ์จะได้ไฟล์ไบนารีเดี่ยวชื่อ **`youtube-downloader-linux`** ในโฟลเดอร์ `dist/`

### C. การสร้างแพ็กเกจแจกจ่ายสไตล์ Linux
มี 2 แนวทางหลักในการส่งมอบแอปพลิเคชัน:
1. **การสร้าง AppImage (ทางเลือกแนะนำ)**: เป็นมาตรฐานไฟล์เดี่ยวที่ทำงานได้บน Linux ทุกดิสโทรโดยไม่ต้องลงไลบรารีเพิ่ม (คล้ายกับไฟล์พกพาของ Windows)
   * ใช้เครื่องมือ **AppImageBuilder** บีบอัดโฟลเดอร์ `dist/` และไฟล์ระบบ
2. **สร้างแพ็กเกจ Debian (`.deb`)**:
   * จัดเตรียมโครงสร้างไดเรกทอรี `DEBIAN/control` เพื่อบอกตำแหน่งติดตั้งของตัวแอป (เช่น ไว้ที่ `/opt/youtube-downloader`)
   * รันคำสั่งประกอบไฟล์: `dpkg-deb --build youtube-downloader-pkg`

---

## 💡 สรุปการตรวจสอบความเข้ากันได้ของระบบ (Compatibility OS Audit)

| หัวข้อการทำงาน | Windows | macOS | Linux |
| :--- | :--- | :--- | :--- |
| **ตัวดึงข้อมูลคุกกี้** | สนับสนุนเบราว์เซอร์หลัก (Registry paths) | สนับสนุน Chrome/Safari/Firefox (ดึงผ่าน `~/Library/Application Support/`) | สนับสนุน Chrome/Firefox (ดึงผ่าน `~/.config/`) |
| **ตัวแปลงสัญญาณ** | โหลดไฟล์อัตโนมัติลง `bin/` (`ffmpeg.exe`) | แนะนำติดตั้งผ่านระบบ `brew` | แนะนำติดตั้งผ่านระบบ `apt/dnf` |
| **ส่วนควบคุม UI/UX** | Single-Page สไตล์ Retro-Pixel | Single-Page สไตล์ Retro-Pixel | Single-Page สไตล์ Retro-Pixel |
| **การคอมไพล์หลัก** | PyInstaller + Inno Setup (`.exe`) | PyInstaller + create-dmg (`.dmg`) | PyInstaller + AppImage/deb (`.deb`) |
