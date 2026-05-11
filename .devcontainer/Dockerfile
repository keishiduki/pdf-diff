FROM mcr.microsoft.com/devcontainers/python:3.11

# tkinter and X11 libs (needed for GUI development/testing on Linux)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-tk \
    tk-dev \
    libx11-dev \
    && rm -rf /var/lib/apt/lists/*
