FROM python:3.11

# Install ImageMagick + Potrace + Inkscape
RUN apt-get update && apt-get install -y \
    imagemagick \
    potrace \
    inkscape \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Copy macOS ImageMagick config into the correct Linux path
COPY imagemagick-config /usr/local/etc/ImageMagick-7/

# Explicitly tell ImageMagick to use this config
ENV MAGICK_CONFIGURE_PATH=/usr/local/etc/ImageMagick-7/

# Expose port
EXPOSE 8080

# Run the application
CMD ["python", "main.py"]
