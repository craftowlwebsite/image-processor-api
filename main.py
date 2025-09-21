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


def convert_png_to_svg_potrace(png_data,
                               alphamax="3.5",
                               opttolerance="3.0",
                               turdsize="250",
                               dither="ordered"):
    """
    Convert PNG bytes to vectorized SVG using Potrace.
    Supports Floyd–Steinberg dithering or ordered dithering.
    """
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_in:
            temp_in.write(png_data)
            temp_in.flush()
            temp_in_path = temp_in.name

        temp_pbm = tempfile.mktemp(suffix=".pbm")
        temp_out_path = tempfile.mktemp(suffix=".svg")

        if dither.lower() == "floyd":
            magick_cmd = [
                "magick", temp_in_path,
                "-colorspace", "Gray",
                "-dither", "FloydSteinberg",
                "-remap", "pattern:gray50",
                temp_pbm
            ]
        else:
            magick_cmd = [
                "magick", temp_in_path,
                "-colorspace", "Gray",
                "-ordered-dither", "o8x8,16",
                temp_pbm
            ]

        subprocess.run(magick_cmd, check=True)

        subprocess.run([
            "potrace", "-s",
            "--turdsize", str(turdsize),
            "--alphamax", str(alphamax),
            "--opttolerance", str(opttolerance),
            "-o", temp_out_path,
            temp_pbm
        ], check=True)

        with open(temp_out_path, "rb") as f:
            svg_data = f.read()

        for p in [temp_in_path, temp_pbm, temp_out_path]:
            if os.path.exists(p):
                os.remove(p)

        return svg_data
    except subprocess.CalledProcessError as e:
        raise Exception(f"Potrace vectorization failed: {e}")
    except Exception as e:
        raise Exception(f"SVG conversion error: {str(e)}")


def convert_png_to_svg_inkscape(png_data,
                                threshold="0.55",
                                smooth_corners=True,
                                optimize=True,
                                suppress_speckles="50"):
    """
    Convert PNG to SVG using Inkscape's headless tracer with tunable options.
    Defaults tuned for smoother, cleaner outlines.
    """
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_in:
            temp_in.write(png_data)
            temp_in.flush()
            temp_in_path = temp_in.name

        temp_out_path = tempfile.mktemp(suffix=".svg")

        # Build command
        cmd = [
            "inkscape", temp_in_path,
            "--export-plain-svg", temp_out_path,
            "--trace-bitmap-mode=brightness",
            f"--trace-bitmap-threshold={threshold}"
        ]

        if smooth_corners:
            cmd.append("--trace-bitmap-smooth-corners")
        if optimize:
            cmd.append("--trace-bitmap-optimize")
        if suppress_speckles:
            cmd.append(f"--trace-bitmap-suppress-speckles={suppress_speckles}")

        subprocess.run(cmd, check=True)

        with open(temp_out_path, "rb") as f:
            svg_data = f.read()

        for p in [temp_in_path, temp_out_path]:
            if os.path.exists(p):
                os.remove(p)

        return svg_data
    except subprocess.CalledProcessError as e:
        raise Exception(f"Inkscape vectorization failed: {e}")
    except Exception as e:
        raise Exception(f"Inkscape conversion error: {str(e)}")


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

        alphamax = data.get('alphamax', "3.5")
        opttolerance = data.get('opttolerance', "3.0")
        turdsize = data.get('turdsize', "250")
        dither = data.get('dither', "ordered")

        svg_data = convert_png_to_svg_potrace(image_data, alphamax, opttolerance, turdsize, dither)
        svg_base64 = base64.b64encode(svg_data).decode('utf-8')

        return jsonify({
            'success': True,
            'engine': 'potrace',
            'svg': svg_base64,
            'size': len(svg_data)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/svg-inkscape', methods=['POST'])
def svg_inkscape():
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

        threshold = data.get('threshold', "0.55")
        smooth_corners = data.get('smooth_corners', True)
        optimize = data.get('optimize', True)
        suppress_speckles = data.get('suppress_speckles', "50")

        svg_data = convert_png_to_svg_inkscape(
            image_data,
            threshold=threshold,
            smooth_corners=smooth_corners,
            optimize=optimize,
            suppress_speckles=suppress_speckles
        )
        svg_base64 = base64.b64encode(svg_data).decode('utf-8')

        return jsonify({
            'success': True,
            'engine': 'inkscape',
            'svg': svg_base64,
            'size': len(svg_data),
            'settings': {
                'threshold': threshold,
                'smooth_corners': smooth_corners,
                'optimize': optimize,
                'suppress_speckles': suppress_speckles
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/process-both', methods=['POST'])
def process_both():
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

        alphamax = data.get('alphamax', "3.5")
        opttolerance = data.get('opttolerance', "3.0")
        turdsize = data.get('turdsize', "250")
        dither = data.get('dither', "ordered")

        processed_png_data = make_transparent(image_data)
        processed_png_base64 = base64.b64encode(processed_png_data).decode('utf-8')

        svg_data = convert_png_to_svg_potrace(image_data, alphamax, opttolerance, turdsize, dither)
        svg_base64 = base64.b64encode(svg_data).decode('utf-8')

        return jsonify({
            'success': True,
            'transparent_png': processed_png_base64,
            'svg': svg_base64,
            'png_size': len(processed_png_data),
            'svg_size': len(svg_data)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'target_size': TARGET_SIZE})


@app.route('/inkscape-version', methods=['GET'])
def inkscape_version():
    try:
        result = subprocess.check_output(["inkscape", "--version"], stderr=subprocess.STDOUT)
        return jsonify({"version": result.decode().strip()})
    except Exception as e:
        return jsonify({"error": str(e)})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
