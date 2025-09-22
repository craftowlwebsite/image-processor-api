from flask import Flask, request, jsonify
from PIL import Image, ImageFilter
import io
import base64
import requests
import subprocess
import tempfile
import os

app = Flask(__name__)

TARGET_SIZE = (4096, 4096)
API_KEY = os.environ.get('API_KEY')


# ---------------------------
# Auth
# ---------------------------
def authenticate():
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return False
    try:
        scheme, token = auth_header.split(' ', 1)
        return scheme.lower() == 'bearer' and token == API_KEY
    except:
        return False


# ---------------------------
# Utilities
# ---------------------------
def _to_int(val, default):
    try:
        return int(val)
    except:
        return default

def _to_float(val, default):
    try:
        return float(val)
    except:
        return default

def _pick_blur_modes(blur_value, blur_pillow_value=None, blur_im_value=None):
    """
    Accepts any of:
      - blur as a number (or numeric string): Pillow GaussianBlur radius BEFORE thresholding
      - blur as "0xN" string: ImageMagick blur AFTER thresholding, before PBM (kept subtle)
      - explicit blur_pillow: overrides Pillow blur radius
      - explicit blur_im: overrides IM blur string

    Returns (pillow_radius_or_None, im_blur_str_or_None)
    """
    # Explicit overrides win
    if blur_pillow_value is not None:
        pr = _to_float(blur_pillow_value, None)
    else:
        pr = None

    if blur_im_value is not None:
        im = str(blur_im_value)
        if not im.startswith("0x"):
            im = None
    else:
        im = None

    # Fallback to single "blur" field
    if pr is None and im is None and blur_value is not None:
        s = str(blur_value).strip()
        if s.startswith("0x"):  # ImageMagick style
            im = s
        else:
            pr = _to_float(s, None)

    return pr, im


# ---------------------------
# Core image ops
# ---------------------------
def make_transparent(image_data, threshold=200, pillow_blur_radius=None):
    """
    1) Optional Pillow GaussianBlur (radius) BEFORE thresholding (works on grayscale content).
    2) Threshold to binary: black vs transparent.
    """
    try:
        img = Image.open(io.BytesIO(image_data))

        # Optional pre-threshold blur to soften edges before cutoff
        if pillow_blur_radius and pillow_blur_radius > 0:
            img = img.filter(ImageFilter.GaussianBlur(radius=float(pillow_blur_radius)))

        if img.mode != 'RGBA':
            img = img.convert('RGBA')

        data = img.getdata()
        new_data = []
        thr = float(threshold)

        for (r, g, b, a) in data:
            # Perceptual brightness
            brightness = (0.299 * r + 0.587 * g + 0.114 * b)
            if brightness < thr and a > 0:
                new_data.append((0, 0, 0, 255))        # Solid black
            else:
                new_data.append((255, 255, 255, 0))    # Fully transparent

        new_img = Image.new('RGBA', img.size)
        new_img.putdata(new_data)

        buf = io.BytesIO()
        new_img.save(buf, format='PNG', dpi=(300, 300))
        buf.seek(0)
        return buf.getvalue()

    except Exception as e:
        raise Exception(f"Error creating transparent version: {str(e)}")


def convert_png_to_svg(png_data,
                       alphamax=3.0,
                       opttolerance=2.0,
                       turdsize=150,
                       im_blur=None,
                       grayscale_first=False,
                       downscale=None):
    """
    ImageMagick step (optional grayscale, optional IM blur, optional downscale) -> PBM
    Potrace -> SVG
    """
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_in:
            temp_in.write(png_data)
            temp_in.flush()
            temp_in_path = temp_in.name

        temp_pbm = tempfile.mktemp(suffix=".pbm")
        temp_out_path = tempfile.mktemp(suffix=".svg")

        # Build ImageMagick command to prepare PBM for Potrace
        magick_cmd = ["magick", temp_in_path]

        # Optional grayscale (can help IM blur act on tones if any remain)
        if grayscale_first:
            magick_cmd.extend(["-colorspace", "Gray"])

        # Optional downscale to reduce staircase artifacts (e.g., "1024x1024")
        if downscale:
            magick_cmd.extend(["-resize", str(downscale)])

        # Optional IM blur (string like "0x0.5", "0x1", etc.)
        if im_blur and isinstance(im_blur, str) and im_blur.startswith("0x"):
            magick_cmd.extend(["-blur", im_blur])

        # Flatten alpha to white and emit PBM
        magick_cmd.extend(["-alpha", "off", temp_pbm])
        subprocess.run(magick_cmd, check=True)

        # Potrace vectorization with smoothing controls
        potrace_cmd = [
            "potrace", "-s",
            "--turdsize", str(int(turdsize)),
            "--alphamax", str(float(alphamax)),
            "--opttolerance", str(float(opttolerance)),
            "-o", temp_out_path,
            temp_pbm
        ]
        subprocess.run(potrace_cmd, check=True)

        with open(temp_out_path, "rb") as f:
            svg_data = f.read()

        # Cleanup
        for p in [temp_in_path, temp_pbm, temp_out_path]:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except:
                pass

        return svg_data

    except subprocess.CalledProcessError as e:
        raise Exception(f"Vectorization failed: {e}")
    except Exception as e:
        raise Exception(f"SVG conversion error: {str(e)}")


# ---------------------------
# Routes
# ---------------------------
@app.route('/transparent', methods=['POST'])
def transparent_only():
    if not authenticate():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data = request.json or {}
        # Input
        if 'url' in data:
            response = requests.get(data['url'])
            image_data = response.content
        elif 'base64' in data:
            image_data = base64.b64decode(data['base64'])
        else:
            return jsonify({'error': 'No image provided'}), 400

        # Params from JSON
        threshold = _to_int(data.get('threshold', 200), 200)

        # Blur selection (supports "blur" numeric for Pillow; "blur_pillow"; "blur_im" "0xN")
        pillow_radius, _ = _pick_blur_modes(
            data.get('blur'),
            blur_pillow_value=data.get('blur_pillow'),
            blur_im_value=data.get('blur_im')
        )

        out_png = make_transparent(image_data, threshold=threshold, pillow_blur_radius=pillow_radius)
        out_b64 = base64.b64encode(out_png).decode('utf-8')

        return jsonify({
            'success': True,
            'processed_image': out_b64,
            'size': len(out_png),
            'threshold': threshold,
            'pillow_blur_radius': pillow_radius
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/svg', methods=['POST'])
def svg_only():
    if not authenticate():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data = request.json or {}

        # Input
        if 'url' in data:
            response = requests.get(data['url'])
            image_data = response.content
        elif 'base64' in data:
            image_data = base64.b64decode(data['base64'])
        else:
            return jsonify({'error': 'No image provided'}), 400

        # Params
        threshold     = _to_int(data.get('threshold', 200), 200)
        alphamax      = _to_float(data.get('alphamax', 3.0), 3.0)
        opttolerance  = _to_float(data.get('opttolerance', 2.0), 2.0)
        turdsize      = _to_int(data.get('turdsize', 150), 150)
        grayscale     = bool(data.get('grayscale_first', False))
        downscale     = data.get('downscale', None)  # e.g. "1024x1024" or None

        # Blur parsing from JSON
        pillow_radius, im_blur = _pick_blur_modes(
            data.get('blur'),
            blur_pillow_value=data.get('blur_pillow'),
            blur_im_value=data.get('blur_im')
        )

        # 1) Binary mask (with optional pre-threshold Pillow blur)
        bin_png = make_transparent(image_data, threshold=threshold, pillow_blur_radius=pillow_radius)

        # 2) Vectorize (with optional IM blur before PBM → Potrace)
        svg_data = convert_png_to_svg(
            bin_png,
            alphamax=alphamax,
            opttolerance=opttolerance,
            turdsize=turdsize,
            im_blur=im_blur,
            grayscale_first=grayscale,
            downscale=downscale
        )

        svg_b64 = base64.b64encode(svg_data).decode('utf-8')
        return jsonify({
            'success': True,
            'svg': svg_b64,
            'size': len(svg_data),
            'threshold': threshold,
            'pillow_blur_radius': pillow_radius,
            'im_blur': im_blur,
            'alphamax': alphamax,
            'opttolerance': opttolerance,
            'turdsize': turdsize,
            'grayscale_first': grayscale,
            'downscale': downscale
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/process-both', methods=['POST'])
def process_both():
    if not authenticate():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data = request.json or {}

        # Input
        if 'url' in data:
            response = requests.get(data['url'])
            image_data = response.content
        elif 'base64' in data:
            image_data = base64.b64decode(data['base64'])
        else:
            return jsonify({'error': 'No image provided'}), 400

        # Params
        threshold     = _to_int(data.get('threshold', 200), 200)
        alphamax      = _to_float(data.get('alphamax', 3.0), 3.0)
        opttolerance  = _to_float(data.get('opttolerance', 2.0), 2.0)
        turdsize      = _to_int(data.get('turdsize', 150), 150)
        grayscale     = bool(data.get('grayscale_first', False))
        downscale     = data.get('downscale', None)  # e.g. "1024x1024" or None

        # Blur parsing (supports both modes)
        pillow_radius, im_blur = _pick_blur_modes(
            data.get('blur'),
            blur_pillow_value=data.get('blur_pillow'),
            blur_im_value=data.get('blur_im')
        )

        # 1) Transparent PNG (with optional Pillow blur before threshold)
        out_png = make_transparent(image_data, threshold=threshold, pillow_blur_radius=pillow_radius)
        out_png_b64 = base64.b64encode(out_png).decode('utf-8')

        # 2) SVG via Potrace (with optional IM blur before PBM)
        svg_data = convert_png_to_svg(
            out_png,
            alphamax=alphamax,
            opttolerance=opttolerance,
            turdsize=turdsize,
            im_blur=im_blur,
            grayscale_first=grayscale,
            downscale=downscale
        )
        svg_b64 = base64.b64encode(svg_data).decode('utf-8')

        return jsonify({
            'success': True,
            'transparent_png': out_png_b64,
            'svg': svg_b64,
            'png_size': len(out_png),
            'svg_size': len(svg_data),
            'threshold': threshold,
            'pillow_blur_radius': pillow_radius,
            'im_blur': im_blur,
            'alphamax': alphamax,
            'opttolerance': opttolerance,
            'turdsize': turdsize,
            'grayscale_first': grayscale,
            'downscale': downscale
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'target_size': TARGET_SIZE})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
