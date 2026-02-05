FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app

EXPOSE 8002

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
