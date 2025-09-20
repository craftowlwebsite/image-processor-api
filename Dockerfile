FROM python:3.11-bullseye

# Install ImageMagick + Potrace + Autotrace
RUN apt-get update && apt-get install -y \
    imagemagick \
    potrace \
    autotrace \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8080

# Run the application
CMD ["python", "main.py"]
