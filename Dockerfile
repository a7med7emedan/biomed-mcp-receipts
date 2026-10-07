# One image holds the bench and every pinned server under test, so a run needs nothing but Docker.
#   docker build -t biomed-mcp-receipts .
#   docker run --rm biomed-mcp-receipts demo
#   mkdir -p runs && chmod 777 runs   # on Linux the container user (uid 10001) must be able to write here
#   docker run --rm -e NCBI_API_KEY -v "$PWD/runs:/home/bench/runs" biomed-mcp-receipts run --oracle record --out runs

FROM node:24-bookworm-slim AS node

FROM python:3.12-slim

# Node 24 for the npm-distributed servers (pubmed-mcp-server needs node >= 24).
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && node --version && npm --version

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /opt/bench
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
# The bench, plus BioMCP pinned to the version its adapter was written against.
RUN pip install . "biomcp-cli==0.9.1"

RUN useradd --create-home --uid 10001 bench
USER bench
WORKDIR /home/bench
# Warm npm's cache with the exact pinned server versions, so the first run starts faster.
RUN npm cache add "@cyanheads/pubmed-mcp-server@2.10.20" "clinicaltrialsgov-mcp-server@2.9.11"

ENTRYPOINT ["bmr"]
CMD ["demo"]
