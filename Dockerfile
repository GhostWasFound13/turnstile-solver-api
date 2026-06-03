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
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install ONLY Camoufox (lighter than Chromium)
RUN python -m camoufox install

COPY . .

# Use Camoufox with 1 thread only
CMD ["python", "api_solver.py", "--host", "0.0.0.0", "--port", "5072", "--thread", "1", "--browser_type", "camoufox"]
