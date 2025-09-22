from flask import Flask, request, jsonify
from PIL import Image
import io
import base64
import requests
import subprocess
import tempfile
import os

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

def make_transparent(image_data, threshold=200):
    """Convert PNG to binary black and transparent with adjustable threshold"""
    try:
        img = Image.open(io.BytesIO(image_data))

        if img.mode != 'RGBA':
            img = img.convert('RGBA')

        data = img.getdata()
        new_data = []

        for item in data:
            r, g, b, a = item
            brightness = (0.299 * r + 0.587 * g + 0.114 * b)

            if brightness < threshold and a > 0:
                new_data.append((0, 0, 0, 255))  # Pure black
            else:
                new_data.append((255, 255, 255, 0))  # Transparent

        new_img = Image.new('RGBA', img.size)
        new_img.putdata(new_data)

        output = io.BytesIO()
        new_img.save(output, format='PNG', dpi=(300, 300))
        output.seek(0)

        return output.getvalue()

    except Exception as e:
        raise Exception(f"Error creating transparent version: {str(e)}")

def convert_png_to_svg(png_data,
                       alphamax="3.0",
                       opttolerance="2.0",
                       turdsize="150",
                       dither="ordered",
                       blur="0x0.5"):
    """Convert PNG bytes to vectorized SVG using Potrace, with optional blur smoothing"""
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_in:
            temp_in.write(png_data)
            temp_in.flush()
            temp_in_path = temp_in.name

        temp_pbm = tempfile.mktemp(suffix=".pbm")
        temp_out_path = tempfile.mktemp(suffix=".svg")

        # Build ImageMagick command
        magick_cmd = ["magick", temp_in_path]
        if blur and blur != "0":
            magick_cmd.extend(["-blur", blur])
        magick_cmd.extend(["-alpha", "off", temp_pbm])

        subprocess.run(magick_cmd, check=True)

        # Run Potrace
        potrace_cmd = [
            "potrace", "-s",
            "--turdsize", str(turdsize),
            "--alphamax", str(alphamax),
            "--opttolerance", str(opttolerance),
            "-o", temp_out_path,
            temp_pbm
        ]
        subprocess.run(potrace_cmd, check=True)

        with open(temp_out_path, "rb") as f:
            svg_data = f.read()

        for p in [temp_in_path, temp_pbm, temp_out_path]:
            if os.path.exists(p):
                os.remove(p)

        return svg_data
    except subprocess.CalledProcessError as e:
        raise Exception(f"Vectorization failed: {e}")
    except Exception as e:
        raise Exception(f"SVG conversion error: {str(e)}")

@app.route('/transparent', methods=['POST'])
def transparent_only():
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

        threshold = int(data.get('threshold', 200))
        processed_data = make_transparent(image_data, threshold)
        processed_base64 = base64.b64encode(processed_data).decode('utf-8')

        return jsonify({
            'success': True,
            'processed_image': processed_base64,
            'size': len(processed_data),
            'threshold': threshold
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/svg', methods=['POST'])
def svg_only():
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

        threshold = int(data.get('threshold', 200))
        processed_png_data = make_transparent(image_data, threshold)

        alphamax = data.get('alphamax', "3.0")
        opttolerance = data.get('opttolerance', "2.0")
        turdsize = data.get('turdsize', "150")
        dither = data.get('dither', "ordered")
        blur = data.get('blur', "0x1")
