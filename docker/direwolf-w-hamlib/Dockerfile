FROM debian:13-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
	git \
	wget \
	ca-certificates \
	build-essential \
	cmake \
	libasound2-dev \
	libudev-dev \
	libavahi-client-dev \
	&& rm -rf /var/lib/apt/lists/*

WORKDIR /src

# Default to 4.7.2 override in docker-compose.yml
ARG HAMLIB_VER=4.7.2
RUN wget -q https://github.com/Hamlib/Hamlib/releases/download/${HAMLIB_VER}/hamlib-${HAMLIB_VER}.tar.gz && \
	tar xf hamlib-${HAMLIB_VER}.tar.gz && \
	cd hamlib-${HAMLIB_VER} && \
	./configure --prefix=/opt/radio && \
	make -j$(nproc) && \
	make install

RUN git clone --depth=1 -b dev https://github.com/wb2osz/direwolf.git direwolf && \
	cd direwolf && \
	mkdir build && cd build && \
	cmake -DCMAKE_INSTALL_PREFIX=/opt/radio -DCMAKE_PREFIX_PATH=/opt/radio .. && \
	make -j$(nproc) && \
	make install

FROM debian:13-slim AS runner

RUN apt-get update && apt-get install -y --no-install-recommends \
	libasound2t64 \
	libudev1 \
	libavahi-client3 \
	netcat-openbsd \
	&& rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/radio /usr/local
RUN ldconfig

COPY docker/direwolf-w-hamlib/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
	CMD nc -z 127.0.0.1 4532 && nc -z 127.0.0.1 8001 || exit 1

CMD ["/entrypoint.sh"]
