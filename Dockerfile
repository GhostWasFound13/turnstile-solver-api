FROM python:3.11-bookworm

WORKDIR /app

COPY . .

RUN pip install -r requirements.txt

RUN python -m playwright install --with-deps chromium
# or:
# RUN python -m patchright install chromium

CMD ["python", "api_solver.py"]
