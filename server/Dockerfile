# 微信云托管（CloudBase Run）镜像
# 现有 FastAPI 后端作为常驻容器运行；云托管默认监听 80 端口。
FROM python:3.11-slim

WORKDIR /app

# 先装依赖（利用层缓存，改代码后不必重装依赖）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 再拷源码
COPY . .

# 云托管控制台「监听端口」请设为 80，与此处一致
EXPOSE 80
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 80"]
