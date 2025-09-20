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
