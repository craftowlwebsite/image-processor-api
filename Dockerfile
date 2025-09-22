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
COPY imagemagick-config /etc/ImageMagick-7/


# Expose port
EXPOSE 8080

# Run the application
CMD ["python", "main.py"]
