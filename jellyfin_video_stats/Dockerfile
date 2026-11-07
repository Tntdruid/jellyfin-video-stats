FROM python:3.12-alpine

RUN apk add --no-cache tzdata

WORKDIR /app
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .
RUN wget -q -O static/echarts.min.js https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js

ENV DATA_DIR=/data
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8099", "--log-level", "warning"]
