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

TARGET_SIZE = (4096, 4096)

# Simple API key authentication
API_KEY = os.environ.get('API_KEY')

def authenticate():
    """Check if request has valid API key"""
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return False
    try:
        scheme, token = auth_header.split(' ', 1)
        return scheme.lower() == 'bearer' and token == API_KEY
    except:
        return False

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
    """Endpoint for background removal - requires authentication"""
    if not authenticate():
        return jsonify({'error': 'Unauthorized'}), 401
        
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

@app.route('/svg', methods=['POST'])
def svg_only():
    """Endpoint for SVG conversion - requires authentication"""
    if not authenticate():
        return jsonify({'error': 'Unauthorized'}), 401
        
    try:
        data = request.json
        
        if 'url' in data:
            response = requests.get(data['url'])
            image_data = response.content
        elif 'base64' in data:
            image_data = base64.b64decode(data['base64'])
        else:
            return jsonify({'error': 'No image provided'}), 400
        
        svg_data = convert_png_to_svg(image_data)
        svg_base64 = base64.b64encode(svg_data).decode('utf-8')
        
        return jsonify({
            'success': True,
            'svg': svg_base64,
            'size': len(svg_data)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'target_size': TARGET_SIZE})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
@app.route('/debug-key', methods=['GET'])

def debug_key():
    return jsonify({
        'api_key_set': bool(os.environ.get('API_KEY')), 
        'api_key_length': len(os.environ.get('API_KEY', '')),
        'api_key_first_10': os.environ.get('API_KEY', '')[:10]
    })
