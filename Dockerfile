FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    XR_PORT=4242

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      openjdk-21-jre-headless \
      curl \
      unzip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Apache FOP 2.6
RUN set -eux; \
    mkdir -p /app/lib/fop /tmp/fop-download; \
    curl -L -o /tmp/fop-download/fop-2.6-bin.zip \
      https://archive.apache.org/dist/xmlgraphics/fop/binaries/fop-2.6-bin.zip; \
    unzip -q /tmp/fop-download/fop-2.6-bin.zip -d /tmp/fop-download; \
    cp /tmp/fop-download/fop-2.6/fop/build/fop.jar /app/lib/fop/; \
    for jar in /tmp/fop-download/fop-2.6/fop/lib/*.jar; do \
      case "$(basename "$jar")" in \
        *xalan*) ;; \
        *) cp "$jar" /app/lib/fop/ ;; \
      esac; \
    done; \
    rm -rf /tmp/fop-download

COPY xrechnung_viewer.py .
COPY templates/ ./templates/
COPY static/ ./static/
COPY 3rdparty/ ./3rdparty/

CMD ["sh", "-c", "python xrechnung_viewer.py --host 0.0.0.0 --port ${XR_PORT}"]
