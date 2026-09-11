FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

WORKDIR /probe

RUN pip install --no-cache-dir playwright==1.62.0

COPY probe.py /probe/probe.py

USER pwuser

ENV PYTHONUNBUFFERED=1

CMD ["python", "/probe/probe.py"]
