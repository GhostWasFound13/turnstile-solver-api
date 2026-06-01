FROM python:3.11-bookworm

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

ENV PLAYWRIGHT_BROWSERS_PATH=/app/.cache/ms-playwright

RUN python -m patchright install chromium

COPY . .

CMD ["python", "api_solver.py"]
