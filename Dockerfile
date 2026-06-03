FROM python:3.11-slim-bookworm

# Install Firefox, Xvfb (virtual display), and dependencies
RUN apt-get update && apt-get install -y \
    wget \
    firefox-esr \
    xvfb \
    libgtk-3-0 \
    libdbus-glib-1-2 \
    libxt6 \
    libx11-xcb1 \
    libxcb-shm0 \
    libxcb-keysyms1 \
    libxcb-randr0 \
    libxcb-render0 \
    libxcb-shape0 \
    libxcb-xfixes0 \
    libxcb-xinerama0 \
    libxcb-xkb1 \
    libxkbcommon-x11-0 \
    && rm -rf /var/lib/apt/lists/*

# Download GeckoDriver
RUN wget -q https://github.com/mozilla/geckodriver/releases/download/v0.34.0/geckodriver-v0.34.0-linux64.tar.gz && \
    tar -xzf geckodriver-v0.34.0-linux64.tar.gz && \
    chmod +x geckodriver && \
    mv geckodriver /usr/local/bin/ && \
    rm geckodriver-v0.34.0-linux64.tar.gz

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api_solver.py .

ENV PYTHONUNBUFFERED=1
ENV DISPLAY=:99

# Start Xvfb virtual display, then run app
RUN echo '#!/bin/bash\n\
Xvfb :99 -screen 0 1280x1024x24 &\n\
sleep 2\n\
python api_solver.py --host 0.0.0.0 --port 5072 --thread 1 --no-headless' > /start.sh && \
    chmod +x /start.sh

EXPOSE 8000

CMD ["/start.sh"]
