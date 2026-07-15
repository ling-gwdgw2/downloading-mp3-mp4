import os
import sys
import platform
import subprocess

def build():
    system = platform.system()
    print(f"🌸 Detecting build host operating system: {system}...")
    
    if system == 'Windows':
        print("⚠️ ERROR: This build script is designed for macOS and Linux. Please use 'build_exe.py' on Windows.")
        sys.exit(1)
        
    print("📦 Installing PyInstaller package dependency...")
    subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"])
    
    # Define build binary properties
    exe_name = "YouTubeDownloader" if system == "Darwin" else "youtube-downloader-linux"
    
    # UNIX path separator for PyInstaller data folders is ':' (whereas Windows uses ';')
    data_sep = ":"
    
    build_args = [
        "pyinstaller",
        "--noconsole",
        "--onefile",
        f"--name={exe_name}",
        f"--add-data=templates{data_sep}templates",
        f"--add-data=static{data_sep}static",
        "app.py"
    ]
    
    print(f"🚀 Running build compilation command:\n{' '.join(build_args)}\n")
    result = subprocess.run(build_args)
    
    if result.returncode == 0:
        print("\n===============================================")
        print("🎉 BUILD COMPLETE SUCCESSFUL! 🌟")
        if system == "Darwin":
            print(f"🍎 macOS App Bundle generated at: dist/{exe_name}.app")
            print("   To package as DMG, you can run: create-dmg dist/YouTubeDownloader.app")
        else:
            print(f"🐧 Linux ELF Binary generated at: dist/{exe_name}")
        print("===============================================")
    else:
        print("\n❌ Build failed! Please verify error details above.")
        sys.exit(1)

if __name__ == "__main__":
    build()
