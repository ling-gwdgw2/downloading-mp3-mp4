# Video & Audio Downloader — System Architecture & Changelog

แอปพลิเคชันดาวน์โหลดวิดีโอและเสียงประสิทธิภาพสูง ทำงานแบบ Local Web Application (เซิร์ฟเวอร์ควบคุมภายในเครื่อง) พัฒนาด้วยภาษา Python (Flask) ร่วมกับแกนดาวน์โหลดประสิทธิภาพสูง `yt-dlp` และตัวแปลงสัญญาณสัญญาณ `FFmpeg` พร้อมส่วนติดต่อผู้ใช้สไตล์ Retro-Pixel ที่มีสีสันสวยงาม เข้าใจง่าย และแสดงผลสถานะแบบเรียลไทม์

---

##  บันทึกการเปลี่ยนแปลงครั้งสำคัญ (Key Changes & Version Upgrades)

###  **Version 2.1.0 (ล่าสุด - 16 กรกฎาคม 2026)**
* **ระบบล้างแคชประหยัด RAM (10s Progress Cleanup)**: ลบ Cache ประวัติดาวน์โหลดและคิวจากหน่วยความจำหลังผ่านไป 10 วินาที ช่วยจัดการปัญหากิน RAM หรือ Memory Leak เมื่อรันโปรแกรมระยะยาว
* **สตรีมปลอดภัยจำกัดเวลา (SSE Timeout Safety)**: กำหนดขีดจำกัดเชื่อมต่อสตรีมสถานะสูงสุด 10 นาที เพื่อความปลอดภัยและตัด Threads ที่ค้างอยู่เบื้องหลังโดยอัตโนมัติ
* **ระบบล็อคการเขียนแท็กเดี่ยว (Duplicate Tagging Prevention)**: ติดตามสถานะไฟล์เพื่อป้องกันไม่ให้ไลบรารี Mutagen ทำการเขียนแท็กและดาวน์โหลดปกอัลบั้มซ้ำหลายครั้งในเซสชันเดียวกัน ช่วยเซฟแบนด์วิดท์และลดความเสี่ยงไฟล์เสียงเสียหาย
* **ป้องกันการรั่วไหลข้อมูลส่วนตัว (Error Sanitizer)**: สกรีนและคัดกรองชื่อพาธส่วนตัว (`C:\Users\username\...`) ออกจากหน้าต่างรายงานข้อผิดพลาดบนหน้าจอ
* **เพิ่มหน้าดาวน์โหลดสุดพรีเมียม (Premium Landing Page)**: เพิ่มหน้า [download_landing.html](file:///c:/Users/vivo9/Desktop/youtube%20mp3%20mp4/download_landing.html) ที่ตกแต่งด้วยธีม Retro-Pixel นีออนสำหรับรองรับการดาวน์โหลดโปรแกรม

###  **Version 2.0.0 (16 กรกฎาคม 2026)**
* **รองรับลิงก์ Spotify (YouTube Search Fallback)**: ถอดรหัส JSON React `initialState` จากหน้าเว็บเพื่อดึงข้อมูลเพลง/ปก และสลับไปค้นหาเวอร์ชันที่ดีที่สุดบน YouTube เพื่อดาวน์โหลดมาแปลงเป็นไฟล์เพลง
* **เขียนข้อมูลและหน้าปกของแท้ (Spotify Metadata & Cover Art Embedding)**: ดึงข้อมูลอย่างเป็นทางการจาก Spotify ฝังลงในแท็ก MP3 (ID3v2) และ M4A (MP4 Atom) หลังแปลงเสร็จเพื่อแสดงผลที่ถูกต้องในเครื่องเล่นเพลงทั่วไป
* **ระบบเช็คลิสต์เลือกเพลง (Playlist Checklist)**: แสดงตารางรายการเพลงใน Playlist ทั้งหมดเพื่อให้ผู้ใช้ติ๊กเลือกดาวน์โหลดเฉพาะบางไฟล์ได้
* **ความคงทนในการโหลดแบบกลุ่ม (Batch Resilience)**: แยกเซสชันดาวน์โหลดในแต่ละแท็กเพลงออกจากกัน ทำให้หากมีเพลงใดเพลงหนึ่งในกลุ่มล้มเหลว ระบบจะข้ามไปทำงานเพลงถัดไปต่อโดยไม่หยุดทำงานทั้งหมด

---

##  แผนภาพสถาปัตยกรรมระบบ (System Architecture)

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

##  วิธีการติดตั้งเพื่อพัฒนาและทดสอบ (Development Guide)

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

##  ขั้นตอนการคอมไพล์เป็นไฟล์เดี่ยวและตัวติดตั้ง (Packaging Guide)

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

---

##  Code Signing Attribution
Free code signing for this project is generously provided by the **[SignPath Foundation](https://signpath.org)**.