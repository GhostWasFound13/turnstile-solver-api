FROM python:3.11-slim-bookworm

# Install minimal dependencies
RUN apt-get update && apt-get install -y \
    libnspr4 \
    libnss3 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Create swap file (512MB) for memory relief
RUN dd if=/dev/zero of=/swapfile bs=1M count=512 && \
    chmod 600 /swapfile && \
    mkswap /swapfile && \
    swapon /swapfile && \
    echo '/swapfile none swap sw 0 0' >> /etc/fstab

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python packages
RUN pip install --no-cache-dir -r requirements.txt

# Camoufox automatically downloads browser when first used
# No separate install command needed

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /app/data /app/cache

# Set environment variables for memory optimization
ENV PYTHONUNBUFFERED=1
ENV NODE_OPTIONS="--max-old-space-size=128"

# Expose port
EXPOSE 5072

# Run with Camoufox (browser will be downloaded on first use)
CMD ["python", "api_solver.py", "--host", "0.0.0.0", "--port", "5072", "--thread", "1", "--browser_type", "camoufox"]
