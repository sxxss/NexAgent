FROM python:3.12-slim

RUN useradd -u 1000 -m sandbox

USER sandbox
WORKDIR /sandbox

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

CMD ["python", "/sandbox/main.py"]
