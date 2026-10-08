FROM debian:bookworm-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake pkg-config libmosquitto-dev nlohmann-json3-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY . .
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON \
    && cmake --build build --parallel \
    && ctest --test-dir build --output-on-failure

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libmosquitto1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --create-home simulator
COPY --from=build /build/build/sentinel-edge /usr/local/bin/sentinel-edge
USER simulator
ENTRYPOINT ["/usr/local/bin/sentinel-edge"]