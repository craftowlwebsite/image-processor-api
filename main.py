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

def check_size(img):
    """Check if image matches target size"""
    return img.size == TARGET_SIZE

def make_transparent(image_data):
    """Convert PNG to binary black and transparent"""
    try:
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
        
        return output.getvalue()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating transparent version: {str(e)}")

def convert_png_to_svg(png_data):
    """Convert PNG bytes to vectorized SVG using Potrace"""
    try:
        # Save temp PNG first
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_in:
            temp_in.write(png_data)
            temp_in.flush()
            temp_in_path = temp_in.name

        temp_pbm = tempfile.mktemp(suffix=".pbm")
        temp_out_path = tempfile.mktemp(suffix=".svg")

        # Convert PNG to PBM (bitmap format for Potrace)
        subprocess.run(
            ["magick", temp_in_path, "-threshold", "50%", temp_pbm],
            check=True
        )

        # Run Potrace to vectorize PBM → SVG
        subprocess.run(
            ["potrace", "-s", "-o", temp_out_path, temp_pbm],
            check=True
        )

        with open(temp_out_path, "rb") as f:
            svg_data = f.read()

        # cleanup
        for p in [temp_in_path, temp_pbm, temp_out_path]:
            if os.path.exists(p):
                os.remove(p)

        return svg_data
    except subprocess.CalledProcessError as e:
        raise Exception(f"Vectorization failed: {e}")
    except Exception as e:
        raise Exception(f"SVG conversion error: {str(e)}")


@app.get("/")
async def root():
    return {"message": "PNG to SVG Converter API", "version": "1.0.0"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/convert")
async def convert_image(file: UploadFile = File(...)):
    """
    Convert a PNG image to SVG and transparent PNG
    Returns both files as base64 encoded strings
    """
    # Validate file type
    if not file.filename.lower().endswith('.png'):
        raise HTTPException(status_code=400, detail="File must be a PNG image")
    
    try:
        # Read the uploaded file
        image_data = await file.read()
        
        # Check image size
        img = Image.open(io.BytesIO(image_data))
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
    uvicorn.run(app, host="0.0.0.0", port=port)
