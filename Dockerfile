FROM python:3.11

# Install build tools and delegate libraries
RUN apt-get update && apt-get install -y \
    build-essential \
    wget \
    pkg-config \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    libgif-dev \
    libwebp-dev \
    libheif-dev \
    libopenjp2-7-dev \
    liblcms2-dev \
    libfreetype6-dev \
    ghostscript \
    libraw-dev \
    libxml2-dev \
    zlib1g-dev \
    liblzma-dev \
    libzstd-dev \
    potrace \
    inkscape \
    && rm -rf /var/lib/apt/lists/*

# Build and install ImageMagick 7.1.1-44 from source
WORKDIR /tmp
RUN wget https://download.imagemagick.org/archive/releases/ImageMagick-7.1.1-44.tar.gz && \
    tar xzf ImageMagick-7.1.1-44.tar.gz && \
    cd ImageMagick-7.1.1-44 && \
    ./configure --with-modules --enable-shared --with-rsvg --with-heic --with-webp && \
    make -j$(nproc) && \
    make install && \
    ldconfig /usr/local/lib && \
    cd .. && rm -rf ImageMagick-7.1.1-44*

# Set working directory
WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Copy macOS ImageMagick config into the correct Linux path
COPY imagemagick-config /usr/local/etc/ImageMagick-7/
ENV MAGICK_CONFIGURE_PATH=/usr/local/etc/ImageMagick-7/

# Expose port
EXPOSE 8080

# Run the application
CMD ["python", "main.py"]
