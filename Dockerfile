FROM python:3.11-slim-bookworm

# Install Chrome/Chromium and dependencies
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    curl \
    gnupg \
    chromium \
    chromium-driver \
    libglib2.0-0 \
    libnss3 \
    libx11-6 \
    libxcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

# Get Chrome version and download matching ChromeDriver
RUN CHROME_VERSION=$(chromium --version | grep -oP '\d+\.\d+\.\d+\.\d+') && \
    CHROME_MAJOR=$(echo $CHROME_VERSION | cut -d. -f1) && \
    echo "Chrome version: $CHROME_VERSION, Major: $CHROME_MAJOR" && \
    wget -q "https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/linux64/chromedriver-linux64.zip" || \
    wget -q "https://storage.googleapis.com/chrome-for-testing-public/${CHROME_MAJOR}.0.0.0/linux64/chromedriver-linux64.zip" && \
    unzip -q chromedriver-linux64.zip && \
    chmod +x chromedriver-linux64/chromedriver && \
    mv chromedriver-linux64/chromedriver /usr/local/bin/chromedriver && \
    rm -rf chromedriver-linux64.zip 

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api_solver.py .

ENV PYTHONUNBUFFERED=1
ENV PATH="/usr/local/bin:${PATH}"

EXPOSE 5072

CMD ["python", "api_solver.py", "--host", "0.0.0.0", "--port", "5072", "--thread", "1", "--no-headless"]
