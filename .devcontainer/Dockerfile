FROM mcr.microsoft.com/devcontainers/python:3.11

# System libs for tkinter and X11 display
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-tk \
    tk-dev \
    libx11-dev \
    libxext-dev \
    && rm -rf /var/lib/apt/lists/*
