FROM ubuntu:24.04

ARG BLENDER_VERSION=5.2.0
ARG BLENDER_SERIES=5.2
ENV BLENDER_DIR=/opt/blender

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libdbus-1-3 \
        libfontconfig1 \
        libgl1 \
        libice6 \
        libsm6 \
        libx11-6 \
        libxext6 \
        libxfixes3 \
        libxi6 \
        libxkbcommon0 \
        libxkbcommon-x11-0 \
        libxrender1 \
        xz-utils \
    && rm -rf /var/lib/apt/lists/*

RUN curl --fail --location --silent --show-error \
        "https://download.blender.org/release/Blender${BLENDER_SERIES}/blender-${BLENDER_VERSION}-linux-x64.tar.xz" \
        --output /tmp/blender.tar.xz \
    && mkdir -p "${BLENDER_DIR}" \
    && tar -xJf /tmp/blender.tar.xz --strip-components=1 -C "${BLENDER_DIR}" \
    && rm /tmp/blender.tar.xz \
    && ln -s "${BLENDER_DIR}/blender" /usr/local/bin/blender

WORKDIR /workspace
COPY . /workspace

ENTRYPOINT ["blender"]
CMD ["--background", "--version"]
