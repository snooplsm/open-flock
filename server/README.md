# Open Flock Server

Open Flock is a mobile flock camera service for Raspberry Pi.

## Mission

Build a field-ready camera node that can:

- stream live video over HTTP
- run plate OCR on-device
- optionally pull GPS from SIM7600 GNSS hardware
- expose live status/telemetry in a HUD

## What Runs

- `server.py` starts:
  - MJPEG stream: `GET /stream.mjpg`
  - web UI: `GET /index.html`
  - event telemetry (HUD): `GET /events` (SSE)
  - profile switch endpoint: `POST /profile?name=<normal|low_light|darkness>`

## Install (Raspberry Pi)

```bash
sudo apt update
sudo apt install -y python3-picamera2 python3-opencv python3-pip python3-venv
```

Create venv that can see apt-installed `picamera2`:

```bash
python3 -m venv --system-site-packages ~/.venv
source ~/.venv/bin/activate
pip install -U pip
pip install -r ~/server/requirements.txt
```

## Run

```bash
source ~/.venv/bin/activate
python ~/server/server.py
```

Open:

- `http://<pi-ip>:8000/index.html`

## Optional GPS (SIM7600)

Enable only when hardware is attached:

```bash
GPS_ENABLE=1 GPS_PORT=/dev/ttyUSB2 GPS_BAUD=115200 python ~/server/server.py
```

Useful check:

```bash
ls /dev/ttyUSB*
```

## Key Environment Variables

- `FPO_MODEL` default: `cct-xs-v1-global-model`
- `FPO_COUNTRY` default: `US`
- `FPO_INTERVAL_SEC` default: `0.5`
- `FPO_ROI` default: `0.20,0.45,0.80,0.75`
- `FPO_TEMP_WARN_C` default: `75`
- `FPO_TEMP_HOT_C` default: `80`
- `FPO_TEMP_CRIT_C` default: `85`
- `GPS_ENABLE` default: `0`
- `GPS_PORT` default: `/dev/ttyUSB2`
- `GPS_BAUD` default: `115200`

## Notes

- OCR only runs when a plate candidate is detected.
- Bounding box is shown only when a plate is detected.
- Hough line detection is used to estimate plate angle and rotate the crop for optimal OCR image quality.
- Thermal governor automatically slows or pauses OCR when Pi temperature is high.
