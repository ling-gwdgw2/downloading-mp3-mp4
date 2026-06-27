from PIL import Image, ImageDraw, ImageFont
import os

def create_placeholder_logo():
    # Create a 256x256 image with a dark background
    img = Image.new('RGBA', (256, 256), color=(30, 30, 30, 255))
    d = ImageDraw.Draw(img)
    
    # Draw a circle
    d.ellipse([20, 20, 236, 236], outline=(255, 62, 62), width=10)
    
    # Draw text "Logo" (or "YD" for YouTube Downloader)
    # detailed font handling is complex without a ttf file, using default
    # But default font is very small.
    # Let's just draw simple shapes or lines to make it look like a play button
    
    # Draw Play Triangle
    d.polygon([(80, 60), (80, 196), (200, 128)], fill=(255, 62, 62), outline=(255, 255, 255))
    
    # Save as PNG
    if not os.path.exists('static/images'):
        os.makedirs('static/images')
    
    img.save('static/images/logo.png')
    print("Created static/images/logo.png")
    
    # Save as ICO (sizes 16, 32, 48, 64, 128, 256)
    img.save('logo.ico', format='ICO', sizes=[(256, 256)])
    print("Created logo.ico")

if __name__ == "__main__":
    create_placeholder_logo()
