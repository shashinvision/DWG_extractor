FROM ubuntu:22.04

# Instalar dependencias
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
  python3.10 \
  python3-pip \
  wget \
  libglu1-mesa \
  libxrender1 \
  libxi6 \
  libxrandr2 \
  libxcursor1 \
  libxinerama1 \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar ODA File Converter (para DWG → DXF)
RUN wget https://download.opendesign.com/guestfiles/ODAFileConverter/ODAFileConverter_QT6_lnxX64_8.3dll_25.6.deb \
  && dpkg -i ODAFileConverter_QT6_lnxX64_8.3dll_25.6.deb || true \
  && apt-get -f install -y \
  && rm ODAFileConverter_QT6_lnxX64_8.3dll_25.6.deb

# Instalar dependencias de Python
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY main.py .

RUN mkdir -p /tmp/conversions && chmod 1777 /tmp/conversions

EXPOSE 8083

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8083", "--workers", "2"]
