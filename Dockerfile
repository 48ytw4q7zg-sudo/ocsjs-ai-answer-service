FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# Container port publishing requires an all-interfaces bind.
ENV HOST=0.0.0.0 DEBUG=false

# 设置工作目录
WORKDIR /app

# 复制依赖文件
COPY requirements.txt requirements-lock.txt ./

# 按锁定文件安装测试过的那组版本（版本范围仍以 requirements.txt 为准）
RUN pip install --no-cache-dir -r requirements-lock.txt

COPY app.py config.py ccswitch.py utils.py logger.py portable_paths.py provider_clients.py provider_settings.py api_docs.md LICENSE gunicorn.conf.py healthcheck.py ./
COPY templates ./templates
COPY static ./static

# 创建日志目录
RUN mkdir -p logs

# 暴露端口
EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["python", "healthcheck.py"]

CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:app"]
