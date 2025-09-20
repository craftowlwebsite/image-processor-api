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
        new_img.save(output, format='PNG', dpi=(300, 300))
        output.seek(0)
        
        return output.getvalue()
        
    except Exception as e:
        raise Exception(f"Error creating transparent version: {str(e)}")


def convert_png_to_svg(png_data):
    """Convert PNG bytes to vectorized SVG using Potrace + Scour optimization"""
    try:
        # Save temp PNG first
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_in:
            temp_in.write(png_data)
            temp_in.flush()
            temp_in_path = temp_in.name

        temp_pbm = tempfile.mktemp(suffix=".pbm")
        temp_out_path = tempfile.mktemp(suffix=".svg")
        temp_scour_out_path = tempfile.mktemp(suffix=".svg")

        # Convert PNG to PBM (bitmap format for Potrace)
        subprocess.run(
            ["magick", temp_in_path, "-threshold", "50%", temp_pbm],
            check=True
        )

        # Run Potrace with tuned parameters
        subprocess.run(
            ["potrace", "-s", "-t", "10", "-a", "2", "-O", "1.5",
             "-o", temp_out_path, temp_pbm],
            check=True
        )

        # Run Scour to optimize/simplify SVG
        subprocess.run(
            ["scour", "-i", temp_out_path, "-o", temp_scour_out_path,
             "--enable-viewboxing", "--enable-id-stripping",
             "--enable-comment-stripping", "--shorten-ids"],
            check=True
        )

        with open(temp_scour_out_path, "rb") as f:
            svg_data = f.read()

        # cleanup
        for p in [temp_in_path, temp_pbm, temp_out_path, temp_scour_out_path]:
            if os.path.exists(p):
                os.remove(p)

        return svg_data
    except subprocess.CalledProcessError as e:
        raise Exception(f"Vectorization failed: {e}")
    except Exception as e:
        raise Exception(f"SVG conversion error: {str(e)}")
