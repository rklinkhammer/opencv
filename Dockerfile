FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        python3 \
        python3-dev \
        python3-gi \
        python3-libgpiod \
        python3-pip \
        python3-venv \
        build-essential \
        gir1.2-gstreamer-1.0 \
        gstreamer1.0-plugins-base \
        gstreamer1.0-plugins-good \
        gstreamer1.0-tools \
        libgl1 \
        libglib2.0-0 \
        v4l-utils \
    && rm -rf /var/lib/apt/lists/*

# system-site-packages makes Ubuntu's gpiod and GObject/GStreamer modules
# available alongside the packages installed in the virtual environment.
RUN python3 -m venv --system-site-packages "$VIRTUAL_ENV" \
    && pip install --no-cache-dir --upgrade pip setuptools wheel

WORKDIR /workspace

COPY pyproject.toml README.md compose.yaml requirements.lock ./
COPY src ./src
COPY typings ./typings
RUN pip install --no-cache-dir -r requirements.lock \
    && pip install --no-cache-dir --no-deps -e . \
    && pip uninstall --yes pip setuptools wheel \
    && apt-get purge -y \
        build-essential \
        python3-dev \
        python3-pip \
        python3-setuptools \
        python3-wheel \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY tests ./tests
COPY scripts ./scripts
COPY ARCHITECTURE.md ./

RUN mkdir -p /workspace/captures/images /workspace/captures/gpio \
    && chown -R ubuntu:ubuntu /workspace

USER ubuntu

CMD ["capture-main", "--help"]
