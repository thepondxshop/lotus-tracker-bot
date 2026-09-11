FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

USER root
WORKDIR /probe

RUN apt-get update \
    && apt-get install -y --no-install-recommends xvfb xauth \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir playwright==1.62.0

COPY probe.py /probe/probe.py
RUN python -m py_compile /probe/probe.py

USER pwuser
ENV PYTHONUNBUFFERED=1

CMD ["xvfb-run", "--auto-servernum", "--server-args=-screen 0 1280x720x24 -nolisten tcp", "python", "/probe/probe.py"]
