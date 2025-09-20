from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import subprocess
from PIL import Image
import tempfile
import zipfile
import io
import base64
from pathlib import Path
import shutil
import uvicorn
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="PNG to SVG Converter API", version="1.0.0")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Updated target size
TARGET_SIZE = (4096, 4096)

def check_dependencies():
    """Check if required dependencies are available"""
    try:
        # Check ImageMagick
        result = subprocess.run(['magick', '-version'], capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("ImageMagick not found or not working")
            return False
        logger.info(f"ImageMagick found: {result.stdout.split()[0:3]}")
        
        # Check Potrace
        result = subprocess.run(['potrace', '--version'], capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("Potrace not found or not working")
            return False
        logger.info(f"Potrace found: {result.stdout.strip()}")
        
        return True
    except Exception as e:
        logger.error(f"Error checking dependencies: {e}")
        return False

def check_size(img):
    """Check if image matches target size"""
    return img.size == TARGET_SIZE

def make_transparent(image_data):
    """Convert PNG to binary black and transparent"""
    try:
        logger.info("Starting transparent conversion")
        # Open the image from bytes
        img = Image.open(io.BytesIO(image_data))
        
        # Convert the image to RGBA if it isn't already
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        
        # Get the image data
        data = img.getdata()
        
        # Create a new list for the modified pixels
        new_data = []
        
        # Process each pixel
        for item in data:
            r, g, b, a = item
            
            # Calculate brightness (weighted RGB values for human perception)
            brightness = (0.299 * r + 0.587 * g + 0.114 * b)
            
            # If pixel is dark enough (below threshold), make it pure black
            # Otherwise, make it transparent
            if brightness < 200 and a > 0:  # Added alpha check
                new_data.append((0, 0, 0, 255))  # Pure black
            else:
                new_data.append((255, 255, 255, 0))  # Transparent
        
        # Create new image with the modified data
        new_img = Image.new('RGBA', img.size)
        new_img.putdata(new_data)
        
        # Save to bytes
        output = io.BytesIO()
        new_img.save(output, format='PNG')
        output.seek(0)
        
        logger.info("Transparent conversion completed successfully")
        return output.getvalue()
    except Exception as e:
        logger.error(f"Error in make_transparent: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating transparent version: {str(e)}")

def convert_png_to_svg(png_data):
    """Convert PNG bytes to vectorized SVG using Potrace"""
    try:
        logger.info("Starting SVG conversion")
        
        # Create temporary files
        temp_in_path = None
        temp_pbm = None
        temp_out_path = None
        
        try:
            # Save temp PNG first
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_in:
                temp_in.write(png_data)
                temp_in.flush()
                temp_in_path = temp_in.name

            temp_pbm = tempfile.mktemp(suffix=".pbm")
            temp_out_path = tempfile.mktemp(suffix=".svg")

            logger.info(f"Converting PNG to PBM: {temp_in_path} -> {temp_pbm}")
            # Convert PNG to PBM (bitmap format for Potrace)
            result = subprocess.run(
                ["magick", temp_in_path, "-threshold", "50%", temp_pbm],
                capture_output=True,
                text=True,
                check=True
            )
            
            if not os.path.exists(temp_pbm):
                raise Exception("PBM file was not created by ImageMagick")

            logger.info(f"Converting PBM to SVG: {temp_pbm} -> {temp_out_path}")
            # Run Potrace to vectorize PBM → SVG
            result = subprocess.run(
                ["potrace", "-s", "-o", temp_out_path, temp_pbm],
                capture_output=True,
                text=True,
                check=True
            )
            
            if not os.path.exists(temp_out_path):
                raise Exception("SVG file was not created by Potrace")

            with open(temp_out_path, "rb") as f:
                svg_data = f.read()

            logger.info("SVG conversion completed successfully")
            return svg_data

        finally:
            # cleanup
            for p in [temp_in_path, temp_pbm, temp_out_path]:
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except:
                        pass

    except subprocess.CalledProcessError as e:
        logger.error(f"Subprocess error: {e}")
        logger.error(f"Stderr: {e.stderr}")
        logger.error(f"Stdout: {e.stdout}")
        raise HTTPException(status_code=500, detail=f"Vectorization failed: {e.stderr or str(e)}")
    except Exception as e:
        logger.error(f"General error in convert_png_to_svg: {e}")
        raise HTTPException(status_code=500, detail=f"SVG conversion error: {str(e)}")

@app.on_event("startup")
async def startup_event():
    """Check dependencies on startup"""
    logger.info("Starting up PNG to SVG Converter API")
    if not check_dependencies():
        logger.error("Required dependencies not found!")
        # Don't exit, but log the error
    else:
        logger.info("All dependencies found successfully")

@app.get("/")
async def root():
    return {"message": "PNG to SVG Converter API", "version": "1.0.0", "status": "running"}

@app.get("/health")
async def health_check():
    deps_ok = check_dependencies()
    return {
        "status": "healthy" if deps_ok else "unhealthy",
        "dependencies": {
            "imagemagick": "available" if deps_ok else "missing",
            "potrace": "available" if deps_ok else "missing"
        }
    }

@app.post("/convert")
async def convert_image(file: UploadFile = File(...)):
    """
    Convert a PNG image to SVG and transparent PNG
    Returns both files as base64 encoded strings
    """
    logger.info(f"Processing file: {file.filename}")
    
    # Validate file type
    if not file.filename.lower().endswith('.png'):
        raise HTTPException(status_code=400, detail="File must be a PNG image")
    
    try:
        # Read the uploaded file
        image_data = await file.read()
        logger.info(f"Read {len(image_data)} bytes from uploaded file")
        
        # Check image size
        img = Image.open(io.BytesIO(image_data))
        logger.info(f"Image size: {img.size}, mode: {img.mode}")
        
        if not check_size(img):
            raise HTTPException(
                status_code=400, 
                detail=f"Image size {img.size} doesn't match required size {TARGET_SIZE}"
            )
        
        # Convert to SVG
        svg_data = convert_png_to_svg(image_data)
        
        # Create transparent version
        transparent_data = make_transparent(image_data)
        
        # Encode as base64 for JSON response
        svg_b64 = base64.b64encode(svg_data).decode('utf-8')
        transparent_b64 = base64.b64encode(transparent_data).decode('utf-8')
        
        logger.info("Conversion completed successfully")
        return JSONResponse({
            "success": True,
            "original_filename": file.filename,
            "svg": {
                "filename": f"{Path(file.filename).stem}.svg",
                "data": svg_b64,
                "size": len(svg_data)
            },
            "transparent_png": {
                "filename": file.filename,
                "data": transparent_b64,
                "size": len(transparent_data)
            }
        })
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in convert_image: {e}")
        raise HTTPException(status_code=500, detail=f"Conversion failed: {str(e)}")

@app.post("/convert-batch")
async def convert_batch(files: list[UploadFile] = File(...)):
    """
    Convert multiple PNG images to SVG and transparent PNG
    Returns a ZIP file containing all converted images
    """
    if len(files) > 10:  # Limit batch size
        raise HTTPException(status_code=400, detail="Maximum 10 files per batch")
    
    results = []
    errors = []
    
    # Create temporary directory for processing
    with tempfile.TemporaryDirectory() as temp_dir:
        svg_dir = os.path.join(temp_dir, "svg")
        transparent_dir = os.path.join(temp_dir, "transparent")
        os.makedirs(svg_dir)
        os.makedirs(transparent_dir)
        
        for file in files:
            if not file.filename.lower().endswith('.png'):
                errors.append(f"{file.filename}: Not a PNG file")
                continue
            
            try:
                # Read the uploaded file
                image_data = await file.read()
                
                # Check image size
                img = Image.open(io.BytesIO(image_data))
                if not check_size(img):
                    errors.append(f"{file.filename}: Wrong size {img.size}, expected {TARGET_SIZE}")
                    continue
                
                # Convert to SVG
                svg_data = convert_png_to_svg(image_data)
                svg_path = os.path.join(svg_dir, f"{Path(file.filename).stem}.svg")
                with open(svg_path, 'wb') as f:
                    f.write(svg_data)
                
                # Create transparent version
                transparent_data = make_transparent(image_data)
                transparent_path = os.path.join(transparent_dir, file.filename)
                with open(transparent_path, 'wb') as f:
                    f.write(transparent_data)
                
                results.append(file.filename)
            
            except Exception as e:
                errors.append(f"{file.filename}: {str(e)}")
        
        if not results:
            raise HTTPException(status_code=400, detail=f"No files processed successfully. Errors: {errors}")
        
        # Create ZIP file
        zip_path = os.path.join(temp_dir, "converted_images.zip")
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            # Add SVG files
            for svg_file in os.listdir(svg_dir):
                zipf.write(os.path.join(svg_dir, svg_file), f"svg/{svg_file}")
            
            # Add transparent PNG files
            for png_file in os.listdir(transparent_dir):
                zipf.write(os.path.join(transparent_dir, png_file), f"transparent/{png_file}")
        
        # Return the ZIP file
        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename="converted_images.zip",
            headers={"X-Processed-Files": str(len(results)), "X-Errors": str(len(errors))}
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Starting server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
