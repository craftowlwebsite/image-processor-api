FROM python:3.11-slim

# Install system dependencies including ImageMagick
RUN apt-get update && apt-get install -y \
    imagemagick \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Configure ImageMagick policy to allow PDF/PNG conversions
RUN sed -i 's/rights="none" pattern="PDF"/rights="read|write" pattern="PDF"/' /etc/ImageMagick-6/policy.xml

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
