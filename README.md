# Video & Audio Downloader — System Architecture & Changelog

แอปพลิเคชันดาวน์โหลดวิดีโอและเสียงประสิทธิภาพสูง ทำงานแบบ Local Web Application (เซิร์ฟเวอร์ควบคุมภายในเครื่อง) พัฒนาด้วยภาษา Python (Flask) ร่วมกับแกนดาวน์โหลดประสิทธิภาพสูง `yt-dlp` และตัวแปลงสัญญาณสัญญาณ `FFmpeg` พร้อมส่วนติดต่อผู้ใช้สไตล์ Retro-Pixel ที่มีสีสันสวยงาม เข้าใจง่าย และแสดงผลสถานะแบบเรียลไทม์

---

## 📌 บันทึกการเปลี่ยนแปลงครั้งสำคัญ (Key Changes & Version Upgrades)

ระบบได้รับการปรับเปลี่ยนสถาปัตยกรรมและโครงสร้างไฟล์เพื่อรองรับเสถียรภาพและขยายขีดความสามารถการดาวน์โหลดระดับสากล ดังนี้:

### 1. **การรวมหน้าจอแสดงผลเดี่ยว (Single-Page UI Consolidation)**
* **การเปลี่ยนแปลง**: ลบหน้าจอแสดงผลการดาวน์โหลดแยกต่างหาก (`templates/downloading.html`) ออกไปทั้งหมด
* **ผลลัพธ์**: ควบรวมตรรกะและแถบความคืบหน้า (Progress Bar) มาไว้ในหน้าจอเดียวที่ **[templates/index.html](file:///c:/Users/vivo9/Desktop/youtube%20mp3%20mp4/templates/index.html)** (Single Page Interface) ส่งผลให้ UX/UI ไหลลื่น รวดเร็ว ไม่ต้องสลับการเปลี่ยนหน้า และควบคุมสถานะคิวการดาวน์โหลดได้อย่างเป็นระเบียบ

### 2. **ระบบสลับคุกกี้เบราว์เซอร์อัตโนมัติ (Browser Cookies Fallback Engine)**
* **การเปลี่ยนแปลง**: เพิ่มตรรกะค้นหาและอ่านข้อมูล Cookies จากโฟลเดอร์เก็บข้อมูลโปรไฟล์ผู้ใช้ของเบราว์เซอร์ยอดนิยมบนเครื่อง Windows (เช่น Chrome, Edge, Firefox, Opera) ลงในฟังก์ชัน `extract_info_with_fallback` และ `download_url_with_fallback` ของ **[app.py](file:///c:/Users/vivo9/Desktop/youtube%20mp3%20mp4/app.py)**
* **ผลลัพธ์**: ป้องกันและแก้ปัญหาการดาวน์โหลดถูกบล็อกหรือจำกัดความเร็วจากระบบภายนอก (เช่น ข้อจำกัดบอตของ YouTube) โดยระบบจะลองสลับนำคุกกี้จากเบราว์เซอร์ต่างๆ มาช่วยผ่านสิทธิ์การเข้าถึงของผู้ใช้จริง หากไม่สำเร็จจะสลับหาเบราว์เซอร์ถัดไป (Fallback Loop) จนกว่าจะโหลดเสร็จสิ้น

### 3. **ถอดสถาปัตยกรรม Native GUI เดิมออก (Native GUI Removal)**
* **การเปลี่ยนแปลง**: นำไฟล์และส่วนติดต่อระบบ Native Python GUI ออกจากคลังโค้ดทั้งหมด (ลบ `gui_app.py`, `create_logo.py`, `logo.png`)
* **ผลลัพธ์**: มุ่งเน้นการพัฒนาแอปพลิเคชันในรูปแบบ Local Web App (Flask backend + UI browser) เต็มตัว ทำให้จัดการเรื่อง Layout CSS ได้สวยงาม มีไดนามิกสีสันสไตล์ Retro และง่ายต่อการปรับขนาดหน้าจอบนอุปกรณ์ต่างๆ

### 4. **เพิ่มชุดภาพโมเดลสัญลักษ์ Phoebe ธีมใหม่ (Aesthetics & Assets Addition)**
* **การเปลี่ยนแปลง**: เพิ่มภาพกราฟิก Phoebe สุดพรีเมียมชุดใหม่เข้าสู่ระบบ ได้แก่ **[phoebe0.png](file:///c:/Users/vivo9/Desktop/youtube%20mp3%20mp4/static/phoebe0.png)**, **[phoebe1.png](file:///c:/Users/vivo9/Desktop/youtube%20mp3%20mp4/static/phoebe1.png)** และ **[phoebe2.png](file:///c:/Users/vivo9/Desktop/youtube%20mp3%20mp4/static/phoebe2.png)**
* **ผลลัพธ์**: ออกแบบและตกแต่งหน้าต่างหลักของ UI ให้ดูมีชีวิตชีวา ยกระดับคุณค่าทางอารมณ์และภาพลักษณ์แบบพรีเมียมให้ผู้ใช้งานได้สัมผัสระหว่างรอสถานะดาวน์โหลด

### 5. **การกำหนดค่าเซฟโฟลเดอร์ Windows อัตโนมัติ (Windows Shell Explorer Registry)**
* **การเปลี่ยนแปลง**: ใช้สิทธิ์ไลบรารี `winreg` เข้าถึง Registry เพื่อหาที่ตั้งโฟลเดอร์ Downloads จริงของระบบ Windows ของแต่ละคอมพิวเตอร์โดยตรง แทนที่จะใช้วิธีฮาร์ดโค้ดพาธตายตัว
* **ผลลัพธ์**: ผู้ใช้งานทั่วไปใช้งานได้ทันทีโดยไม่ต้องไปสืบค้นหาตำแหน่งบันทึกไฟล์ตั้งแต่เริ่มเปิดใช้งานโปรแกรมครั้งแรก

---

## 🗺️ แผนภาพสถาปัตยกรรมระบบ (System Architecture)

แผนภาพแสดงการประสานการทำงานระหว่าง Client, Flask Backend และแกนประมวลผล yt-dlp/FFmpeg:

```mermaid
graph TD
    %% Frontend Components
    subgraph Client Browser [เว็บเบราว์เซอร์ของผู้ใช้]
        UI[Retro-Pixel UX/UI HTML & CSS]
        AJAX[JavaScript Fetch / API Call]
        SSE[EventSource Client / SSE Listener]
    end

    %% Backend Flask Components
    subgraph Flask Local Server [เซิร์ฟเวอร์ควบคุมภายในเครื่อง]
        APP[app.py - Flask Controller]
        MW[check_ffmpeg Middleware]
        CORE_LOAD[Dynamic Engine Loader]
        TH_MGR[Background Thread Manager]
        TR_MGR[Session & Progress Tracker]
    end

    %% Execution Engine
    subgraph Downloader Core [แกนประมวลผล]
        YTDL[yt_dlp Library Core]
        FFMPEG[FFmpeg Essentials Binary]
    end

    %% Target Sources
    subgraph Target Websites [เว็บไซต์ปลายทาง]
        YT[YouTube API / Streams]
        OTHER[1,000+ Video/Audio Sites]
    end

    %% Connections
    UI --> AJAX
    UI --> SSE
    AJAX -->|1. ขอข้อมูล / เริ่มดาวน์โหลด| APP
    SSE -->|3. ติดตามสถานะแบบสด| APP
    APP --> MW
    MW -->|ตรวจหา| FFMPEG
    APP --> CORE_LOAD
    CORE_LOAD -->|โหลดแกนนำเข้า| YTDL
    APP --> TH_MGR
    TH_MGR -->|รันเบื้องหลัง| YTDL
    YTDL -->|ดึงข้อมูลมัลติมีเดีย| Target Websites
    YTDL -->|รวมไฟล์ / แปลงไฟล์| FFMPEG
    YTDL -->|2. รายงานสถานะ| TR_MGR
    TR_MGR -->|4. ส่งข้อมูลสถานะเรียลไทม์| SSE
```

---

## 📦 วิธีการติดตั้งเพื่อพัฒนาและทดสอบ (Development Guide)

### 1. **สิ่งที่ต้องเตรียม (Prerequisites)**
* Python เวอร์ชัน 3.8 หรือสูงกว่า
* ตัวแปลงสัญญาณ FFmpeg (หากรันครั้งแรก ระบบมี Middleware แนะนำดาวน์โหลดและตั้งค่าพาธลงโฟลเดอร์ `bin/` อัตโนมัติ)

### 2. **ขั้นตอนการรันเพื่อทดสอบโลคอล**
```bash
# 1. โคลนคลังโค้ดลงมาในเครื่อง
git clone https://github.com/ling-gwdgw2/downloading-mp3-mp4.git
cd downloading-mp3-mp4

# 2. สร้างสภาพแวดล้อมจำลอง (Virtual Environment)
python -m venv .venv
.venv\Scripts\activate

# 3. ติดตั้งไลบรารีจำเป็น
pip install -r requirements.txt

# 4. เริ่มรันแอปพลิเคชัน
python app.py
```
*ตัวระบบโลคอลจะเริ่มทำงานที่ http://127.0.0.1:5000 และจะเปิดเว็บเบราว์เซอร์หน้าจอดาวน์โหลดหลักขึ้นมาให้โดยอัตโนมัติ*

---

## 🛠️ ขั้นตอนการคอมไพล์เป็นไฟล์เดี่ยวและตัวติดตั้ง (Packaging Guide)

### 1. **คอมไพล์ด้วย PyInstaller**
เราใช้สคริปต์คอมไพล์เฉพาะ **[build_exe.py](file:///c:/Users/vivo9/Desktop/youtube%20mp3%20mp4/build_exe.py)** ในการควบคุมพารามิเตอร์ของ PyInstaller ทั้งหมด (แนบเทมเพลตและไลบรารีแกน `curl_cffi`):
```bash
python build_exe.py
```
ผลลัพธ์ไฟล์เดี่ยวสำเร็จรูปจะปรากฏขึ้นที่โฟลเดอร์ **`dist/YouTubeDownloader.exe`** แบบซ่อนหน้าจอคอนโซลดำ (`--noconsole`)

### 2. **สร้างตัวติดตั้ง Windows ด้วย Inno Setup**
1. เปิดโปรแกรม **Inno Setup Compiler**
2. เปิดไฟล์สคริปต์ **[setup.iss](file:///c:/Users/vivo9/Desktop/youtube%20mp3%20mp4/setup.iss)** ผ่านโปรแกรม
3. กดปุ่ม **Compile** (คีย์ลัด F9) เพื่อรวมโฟลเดอร์ `dist/` ออกมาเป็นไฟล์ติดตั้งตัวเดียว
4. ตัวติดตั้งสำเร็จรูปจะถูกบันทึกไว้ในโฟลเดอร์ **`installer_output/YouTubeDownloaderSetup.exe`**