from flask import Flask, request, jsonify, send_file
from PIL import Image
import io
import base64
import requests
import subprocess
import tempfile
import os
from pathlib import Path

app = Flask(__name__)

TARGET_SIZE = (4096, 4096)  # Updated to 4096x4096

def check_size(img):
    """Check if image matches target size"""
    return img.size == TARGET_SIZE

def make_transparent(image_data):
    """Convert PNG to binary black and transparent"""
    try:
        img = Image.open(io.BytesIO(image_data))
        
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        
        data = img.getdata()
        new_data = []
        
        for item in data:
            r, g, b, a = item
            brightness = (0.299 * r + 0.587 * g + 0.114 * b)
            
            if brightness < 200 and a > 0:
                new_data.append((0, 0, 0, 255))  # Pure black
            else:
                new_data.append((255, 255, 255, 0))  # Transparent
        
        new_img = Image.new('RGBA', img.size)
        new_img.putdata(new_data)
        
        output = io.BytesIO()
        new_img.save(output, format='PNG')
        output.seek(0)
        
        return output.getvalue()
        
    except Exception as e:
        raise Exception(f"Error creating transparent version: {str(e)}")

def convert_png_to_svg(png_data):
    """Convert PNG data to SVG using ImageMagick"""
    try:
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_png:
            temp_png.write(png_data)
            temp_png_path = temp_png.name
        
        temp_svg_path = temp_png_path.replace('.png', '.svg')
        
        subprocess.run([
            'magick',
            temp_png_path,
            '-background', 'none',
            '-density', '300',
            temp_svg_path
        ], check=True)
        
        with open(temp_svg_path, 'rb') as f:
            svg_data = f.read()
        
        os.unlink(temp_png_path)
        os.unlink(temp_svg_path)
        
        return svg_data
        
    except subprocess.CalledProcessError as e:
        raise Exception(f"ImageMagick conversion failed: {str(e)}")
    except Exception as e:
        raise Exception(f"SVG conversion error: {str(e)}")

@app.route('/transparent', methods=['POST'])
def transparent_only():
    """Endpoint for just background removal"""
    try:
        data = request.json
        
        if 'url' in data:
            response = requests.get(data['url'])
            image_data = response.content
        elif 'base64' in data:
            image_data = base64.b64decode(data['base64'])
        else:
            return jsonify({'error': 'No image provided'}), 400
        
        processed_data = make_transparent(image_data)
        processed_base64 = base64.b64encode(processed_data).decode('utf-8')
        
        return jsonify({
            'success': True,
            'processed_image': processed_base64,
            'size': len(processed_data)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'target_size': TARGET_SIZE})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
