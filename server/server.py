#!/usr/bin/python3

import io
import json
import logging
import os
import re
import signal
import socketserver
import subprocess
import time
from http import server
from threading import Condition, Event, Lock, Thread
from urllib.parse import parse_qs, urlparse

from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput

PAGE = """\
<html>
<head>
<style>
html, body { margin: 0; padding: 0; background: #000; color: #fff; font-family: monospace; }
#video-wrap {
  position: relative;
  width: 1440px;
  height: 1080px;
  max-width: 100vw;
  max-height: 100vh;
}
#stream, #overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  display: block;
}
#stream { object-fit: contain; }
#overlay { pointer-events: none; }
#hud {
  position: fixed;
  top: 10px;
  left: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.55);
  border: 1px solid rgba(255, 255, 255, 0.2);
  line-height: 1.4;
  white-space: pre;
}
#controls {
  position: fixed;
  top: 10px;
  right: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.55);
  border: 1px solid rgba(255, 255, 255, 0.2);
}
#controls select, #controls button {
  font-family: monospace;
  font-size: 14px;
}
</style>
<title>picamera2 MJPEG streaming demo</title>
</head>
<body>
<div id="video-wrap">
  <img id="stream" src="stream.mjpg" width="1440" height="1080" />
  <canvas id="overlay"></canvas>
</div>
<div id="hud">loading...</div>
<div id="controls">
  <label for="profile">Profile:</label>
  <select id="profile">
    <option value="normal">normal</option>
    <option value="low_light">low_light</option>
    <option value="darkness">darkness</option>
  </select>
  <button id="apply">Apply</button>
</div>
<script>
let profileUiLockUntilMs = 0;

function renderHud(s) {
  const hud = document.getElementById('hud');
  const profile = document.getElementById('profile');
  const profileActive = (document.activeElement === profile) || (Date.now() < profileUiLockUntilMs);
  if (!profileActive && s.profile && profile.value !== s.profile) {
    profile.value = s.profile;
  }
  hud.textContent =
    'FPS: ' + (s.fps || 0).toFixed(1) + '\\n' +
    'Clients: ' + (s.clients || 0) + '\\n' +
    'Frames: ' + (s.frames || 0) + '\\n' +
    'Profile: ' + (s.profile || '-') + '\\n' +
    'Exposure: ' + (s.exposure_us || 0) + ' us\\n' +
    'Gain: ' + ((s.analogue_gain || 0)).toFixed(2) + 'x\\n' +
    'OCR: ' + (s.ocr_status || '-') + '\\n' +
    'Plate: ' + (s.ocr_plate || '-') + '\\n' +
    'OCR conf: ' + (((s.ocr_confidence || 0) * 100)).toFixed(1) + '%\\n' +
    'OCR latency: ' + ((s.ocr_latency_ms || 0)).toFixed(1) + ' ms\\n' +
    'Plate found: ' + ((s.plate_detected) ? 'yes' : 'no') + '\\n' +
    'Plate angle: ' + ((s.plate_angle_deg || 0)).toFixed(1) + ' deg\\n' +
    'GPS: ' + (s.gps_status || 'disabled') + '\\n' +
    'Lat,Lon: ' + ((s.gps_lat || 0).toFixed(6)) + ', ' + ((s.gps_lon || 0).toFixed(6)) + '\\n' +
    'Speed(kn): ' + ((s.gps_speed_knots || 0).toFixed(1)) + '\\n' +
    'Fix UTC: ' + (s.gps_utc || '-') + '\\n' +
    'Resolution: ' + (s.resolution || '-') + '\\n' +
    'Bitrate: ' + ((s.bitrate_mbps || 0)).toFixed(1) + ' Mbps\\n' +
    'Uptime: ' + ((s.uptime_sec || 0)).toFixed(1) + 's';
  drawPlateOverlay(s);
}

function drawPlateOverlay(s) {
  const canvas = document.getElementById('overlay');
  const img = document.getElementById('stream');
  if (!canvas || !img) return;

  const w = Math.max(1, img.clientWidth || 0);
  const h = Math.max(1, img.clientHeight || 0);
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, w, h);

  if (!s.plate_detected) return;
  const b = s.plate_bbox_norm;
  if (!Array.isArray(b) || b.length !== 4) return;
  let [x1, y1, x2, y2] = b.map(Number);
  if (![x1, y1, x2, y2].every(Number.isFinite)) return;
  if (x2 <= x1 || y2 <= y1) return;

  x1 *= w; y1 *= h; x2 *= w; y2 *= h;
  const color = '#00ff66';
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);

  ctx.fillStyle = color;
  ctx.font = '14px monospace';
  const label = `plate ${((s.plate_angle_deg || 0)).toFixed(1)}deg`;
  ctx.fillText(label, x1 + 4, Math.max(14, y1 - 6));
}

function startHudEvents() {
  const hud = document.getElementById('hud');
  const ev = new EventSource('/events');
  ev.addEventListener('stats', (msg) => {
    try {
      renderHud(JSON.parse(msg.data));
    } catch (e) {
      hud.textContent = 'HUD parse error: ' + e;
    }
  });
  ev.onerror = () => {
    hud.textContent = 'HUD disconnected, retrying...';
  };
}

startHudEvents();

document.getElementById('profile').addEventListener('focus', () => {
  profileUiLockUntilMs = Date.now() + 5000;
});
document.getElementById('profile').addEventListener('change', () => {
  profileUiLockUntilMs = Date.now() + 3000;
});
document.getElementById('profile').addEventListener('blur', () => {
  profileUiLockUntilMs = Date.now() + 1000;
});

document.getElementById('apply').addEventListener('click', async () => {
  const profile = document.getElementById('profile').value;
  profileUiLockUntilMs = Date.now() + 3000;
  try {
    const res = await fetch('/profile?name=' + encodeURIComponent(profile), { method: 'POST' });
    if (!res.ok) {
      throw new Error('HTTP ' + res.status);
    }
  } catch (e) {
    alert('Failed to apply profile: ' + e);
  }
});
</script>
</body>
</html>
"""


class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = Condition()
        self.lock = Lock()
        self.start_ts = time.time()
        self.last_frame_ts = self.start_ts
        self.frame_count = 0
        self.total_bytes = 0

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()
        now = time.time()
        with self.lock:
            self.frame_count += 1
            self.total_bytes += len(buf)
            self.last_frame_ts = now

    def stats(self):
        now = time.time()
        with self.lock:
            uptime = max(now - self.start_ts, 1e-6)
            fps = self.frame_count / uptime
            mbps = (self.total_bytes * 8.0) / uptime / 1_000_000.0
            return {
                "fps": fps,
                "frames": self.frame_count,
                "uptime_sec": uptime,
                "bitrate_mbps": mbps,
            }


class StreamingHandler(server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/':
            self.send_response(301)
            self.send_header('Location', '/index.html')
            self.end_headers()
        elif path == '/events-once':
            stats = get_cached_metadata(max_age_sec=1.0)
            body = json.dumps(stats).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Content-Length', len(body))
            self.end_headers()
            self.wfile.write(body)
        elif path == '/events':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            try:
                while True:
                    stats = get_cached_metadata(max_age_sec=1.0)
                    payload = json.dumps(stats, separators=(",", ":"))
                    self.wfile.write(f"event: stats\ndata: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    time.sleep(1.0)
            except Exception:
                pass
        elif path == '/index.html':
            content = PAGE.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        elif path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            add_client()
            try:
                while True:
                    with output.condition:
                        output.condition.wait()
                        frame = output.frame
                    meta = get_cached_metadata(max_age_sec=1.0)
                    maybe_log_stream_stats(meta, min_interval_sec=1.0)
                    self.wfile.write(b'--FRAME\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', len(frame))
                    self.end_headers()
                    self.wfile.write(frame)
                    self.wfile.write(b'\r\n')
            except Exception as e:
                logging.warning(
                    'Removed streaming client %s: %s',
                    self.client_address, str(e))
            finally:
                remove_client()
        else:
            self.send_error(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path != '/profile':
            self.send_error(404)
            self.end_headers()
            return

        params = parse_qs(parsed.query)
        profile = params.get('name', [''])[0].strip()
        if not profile:
            self.send_error(400, "missing profile name")
            self.end_headers()
            return

        ok, error = apply_camera_profile(profile)
        if not ok:
            self.send_error(400, error)
            self.end_headers()
            return

        body = json.dumps({"ok": True, "profile": profile}).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)


class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


client_count = 0
client_lock = Lock()


def add_client():
    global client_count
    with client_lock:
        client_count += 1


def remove_client():
    global client_count
    with client_lock:
        client_count = max(client_count - 1, 0)


def get_client_count():
    with client_lock:
        return client_count


CAMERA_PROFILES = {
    "normal": {
        "AeEnable": False,
        "ExposureTime": 20000,
        "AnalogueGain": 4.0,
        "FrameDurationLimits": (33333, 33333),
    },
    "low_light": {
        "AeEnable": False,
        "ExposureTime": 100000,
        "AnalogueGain": 8.0,
        "FrameDurationLimits": (100000, 100000),
    },
    "darkness": {
        "AeEnable": False,
        "ExposureTime": 200000,
        "AnalogueGain": 12.0,
        "FrameDurationLimits": (200000, 200000),
    },
}
camera_lock = Lock()
current_profile = "normal"
current_controls = dict(CAMERA_PROFILES["normal"])


def get_current_profile():
    with camera_lock:
        return current_profile


def get_current_controls():
    with camera_lock:
        return dict(current_controls)


def apply_camera_profile(profile_name):
    global current_profile, current_controls
    requested = CAMERA_PROFILES.get(profile_name)
    if requested is None:
        return False, "unknown profile"

    # Prefer full profile, but some sensors/drivers reject certain controls
    # while streaming (notably FrameDurationLimits). Fall back progressively.
    attempts = []
    attempts.append(dict(requested))
    safe = {}
    for k in ("AeEnable", "ExposureTime", "AnalogueGain"):
        if k in requested:
            safe[k] = requested[k]
    if safe and safe != attempts[0]:
        attempts.append(safe)

    last_exc = None
    applied = None
    try:
        with camera_lock:
            for candidate in attempts:
                try:
                    picam2.set_controls(candidate)
                    applied = dict(candidate)
                    break
                except Exception as exc:
                    last_exc = exc
                    logging.warning(
                        "Profile %s partial apply failed for controls=%s: %s",
                        profile_name,
                        candidate,
                        exc,
                    )
            if applied is None:
                raise RuntimeError(str(last_exc) if last_exc else "failed to apply controls")

            # Read back metadata so HUD reflects what camera is actually using.
            meta = {}
            try:
                meta = picam2.capture_metadata() or {}
            except Exception:
                meta = {}

            current_profile = profile_name
            current_controls = dict(applied)
            if "ExposureTime" in meta:
                current_controls["ExposureTime"] = int(meta["ExposureTime"])
            if "AnalogueGain" in meta:
                current_controls["AnalogueGain"] = float(meta["AnalogueGain"])
        logging.info("Applied camera profile: %s controls=%s", profile_name, current_controls)
        return True, ""
    except Exception as exc:
        logging.exception("Failed to apply profile %s", profile_name)
        return False, str(exc)


def _parse_roi(value):
    default = (0.20, 0.45, 0.80, 0.75)
    if not value:
        return default
    try:
        parts = [float(x.strip()) for x in value.split(",")]
        if len(parts) != 4:
            return default
        x1, y1, x2, y2 = parts
        if not (0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0):
            return default
        return (x1, y1, x2, y2)
    except Exception:
        return default


OCR_MODEL = os.getenv("FPO_MODEL", "cct-xs-v1-global-model")
OCR_COUNTRY = os.getenv("FPO_COUNTRY", "US").upper()
OCR_INTERVAL_SEC = float(os.getenv("FPO_INTERVAL_SEC", "0.5"))
OCR_ROI = _parse_roi(os.getenv("FPO_ROI"))
TEMP_WARN_C = float(os.getenv("FPO_TEMP_WARN_C", "75.0"))
TEMP_HOT_C = float(os.getenv("FPO_TEMP_HOT_C", "80.0"))
TEMP_CRIT_C = float(os.getenv("FPO_TEMP_CRIT_C", "85.0"))
GPS_ENABLE = os.getenv("GPS_ENABLE", "0").strip().lower() in ("1", "true", "yes", "on")
GPS_PORT = os.getenv("GPS_PORT", "/dev/ttyUSB2")
GPS_BAUD = int(os.getenv("GPS_BAUD", "115200"))
GPS_INTERVAL_SEC = float(os.getenv("GPS_INTERVAL_SEC", "1.0"))
ocr_lock = Lock()
ocr_state = {
    "ocr_status": "init",
    "ocr_plate": "",
    "ocr_confidence": 0.0,
    "ocr_latency_ms": 0.0,
    "plate_detected": False,
    "plate_angle_deg": 0.0,
    "plate_bbox_norm": [],
}
ocr_stop = Event()
ocr_recognizer = None
ocr_backend = "none"
ocr_model_in_use = ""
np_module = None
US_PLATE_RE = re.compile(r"^[A-Z0-9]{5,8}$")
thermal_lock = Lock()
thermal_state = {
    "temp_c": 0.0,
    "zone": "unknown",
    "ocr_scale": 1.0,
    "ocr_paused": False,
    "status": "init",
}
gps_lock = Lock()
gps_state = {
    "gps_status": "disabled",
    "gps_enabled": GPS_ENABLE,
    "gps_port": GPS_PORT,
    "gps_lat": 0.0,
    "gps_lon": 0.0,
    "gps_speed_knots": 0.0,
    "gps_course_deg": 0.0,
    "gps_utc": "",
    "gps_sats_used": 0,
}


def set_ocr_state(
    status=None,
    plate=None,
    confidence=None,
    latency_ms=None,
    plate_detected=None,
    plate_angle_deg=None,
    plate_bbox_norm=None,
):
    with ocr_lock:
        if status is not None:
            ocr_state["ocr_status"] = status
        if plate is not None:
            ocr_state["ocr_plate"] = plate
        if confidence is not None:
            ocr_state["ocr_confidence"] = float(confidence)
        if latency_ms is not None:
            ocr_state["ocr_latency_ms"] = float(latency_ms)
        if plate_detected is not None:
            ocr_state["plate_detected"] = bool(plate_detected)
        if plate_angle_deg is not None:
            ocr_state["plate_angle_deg"] = float(plate_angle_deg)
        if plate_bbox_norm is not None:
            ocr_state["plate_bbox_norm"] = list(plate_bbox_norm)


def get_ocr_stats():
    with ocr_lock:
        return dict(ocr_state)


def set_gps_state(**kwargs):
    with gps_lock:
        gps_state.update(kwargs)


def get_gps_stats():
    with gps_lock:
        return dict(gps_state)


def get_live_metadata():
    stats = output.stats()
    controls = get_current_controls()
    meta = {
        "ts": time.time(),
        "fps": stats.get("fps", 0.0),
        "frames": stats.get("frames", 0),
        "clients": get_client_count(),
        "profile": get_current_profile(),
        "exposure_us": int(controls.get("ExposureTime", 0)),
        "analogue_gain": float(controls.get("AnalogueGain", 0.0)),
        "resolution": "1440x1080",
        "bitrate_mbps": stats.get("bitrate_mbps", 0.0),
        "uptime_sec": stats.get("uptime_sec", 0.0),
    }
    meta.update(get_ocr_stats())
    with thermal_lock:
        meta.update(dict(thermal_state))
    meta.update(get_gps_stats())
    return meta


meta_cache_lock = Lock()
meta_cache = {"ts_monotonic": 0.0, "meta": {}}
stream_log_lock = Lock()
stream_log_last_ts = 0.0


def get_cached_metadata(max_age_sec=1.0):
    now = time.monotonic()
    with meta_cache_lock:
        age = now - meta_cache["ts_monotonic"]
        if age >= max_age_sec or not meta_cache["meta"]:
            meta = get_live_metadata()
            meta_cache["meta"] = meta
            meta_cache["ts_monotonic"] = now
        return dict(meta_cache["meta"])


def maybe_log_stream_stats(meta, min_interval_sec=1.0):
    global stream_log_last_ts
    now = time.monotonic()
    with stream_log_lock:
        if now - stream_log_last_ts < min_interval_sec:
            return
        stream_log_last_ts = now
    logging.info(
        "stream fps=%.1f clients=%d profile=%s exp_us=%d gain=%.2f plate=%s conf=%.1f%%",
        float(meta.get("fps", 0.0)),
        int(meta.get("clients", 0)),
        str(meta.get("profile", "-")),
        int(meta.get("exposure_us", 0)),
        float(meta.get("analogue_gain", 0.0)),
        str(meta.get("ocr_plate", "")) or "-",
        float(meta.get("ocr_confidence", 0.0)) * 100.0,
    )


def init_ocr():
    global ocr_recognizer, np_module, ocr_backend, ocr_model_in_use
    try:
        import numpy as np
        np_module = np
    except Exception as exc:
        set_ocr_state(status=f"disabled:numpy ({exc})")
        return

    try:
        from fast_plate_ocr import LicensePlateRecognizer
        ocr_recognizer = LicensePlateRecognizer(OCR_MODEL)
        ocr_backend = "LicensePlateRecognizer"
        ocr_model_in_use = OCR_MODEL
        set_ocr_state(status=f"ready:{ocr_backend}:{ocr_model_in_use}")
        return
    except Exception:
        pass

    try:
        from fast_plate_ocr import ONNXPlateRecognizer
        # ONNXPlateRecognizer is an older API path tied to legacy models.
        # For US-only usage with modern model hub entries, require the newer
        # LicensePlateRecognizer backend instead of silently using legacy behavior.
        _ = ONNXPlateRecognizer
        set_ocr_state(status="disabled:upgrade fast-plate-ocr for US models")
        return
    except Exception as exc:
        set_ocr_state(status=f"disabled:fast_plate_ocr ({exc})")


def decode_jpeg_to_bgr(frame_bytes):
    if np_module is None:
        return None
    try:
        import cv2
        arr = np_module.frombuffer(frame_bytes, dtype=np_module.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:
        pass
    try:
        from PIL import Image
        import io as _io
        img = Image.open(_io.BytesIO(frame_bytes)).convert("RGB")
        rgb = np_module.array(img)
        # Convert RGB -> BGR for OpenCV-style processing.
        return rgb[:, :, ::-1]
    except Exception:
        return None


def crop_plate_roi(img):
    if img is None:
        return None
    h, w = img.shape[:2]
    x1 = int(OCR_ROI[0] * w)
    y1 = int(OCR_ROI[1] * h)
    x2 = int(OCR_ROI[2] * w)
    y2 = int(OCR_ROI[3] * h)
    if x2 <= x1 or y2 <= y1:
        return img
    return img[y1:y2, x1:x2]


def roi_bbox(img):
    if img is None:
        return None
    h, w = img.shape[:2]
    x1 = int(OCR_ROI[0] * w)
    y1 = int(OCR_ROI[1] * h)
    x2 = int(OCR_ROI[2] * w)
    y2 = int(OCR_ROI[3] * h)
    if x2 <= x1 or y2 <= y1:
        return (0, 0, w, h)
    return (x1, y1, x2, y2)


def bbox_to_norm(bbox, width, height):
    if not bbox or width <= 0 or height <= 0:
        return []
    x1, y1, x2, y2 = bbox
    return [
        max(0.0, min(1.0, x1 / float(width))),
        max(0.0, min(1.0, y1 / float(height))),
        max(0.0, min(1.0, x2 / float(width))),
        max(0.0, min(1.0, y2 / float(height))),
    ]


def _rotate_image_keep_size(img, angle_deg):
    try:
        import cv2
    except Exception:
        return img, None
    h, w = img.shape[:2]
    center = (w * 0.5, h * 0.5)
    mat = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    rot = cv2.warpAffine(
        img,
        mat,
        (w, h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return rot, mat


def _detect_plate_bbox_hough(img):
    try:
        import cv2
    except Exception:
        return None, 0.0

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 80, 180)

    min_len = max(40, int(w * 0.06))
    lines = cv2.HoughLinesP(
        edges,
        1,
        np_module.pi / 180.0,
        threshold=80,
        minLineLength=min_len,
        maxLineGap=24,
    )

    angles = []
    if lines is not None:
        for ln in lines[:, 0]:
            x1, y1, x2, y2 = [int(v) for v in ln]
            dx = x2 - x1
            dy = y2 - y1
            seg_len = float((dx * dx + dy * dy) ** 0.5)
            if seg_len < min_len:
                continue
            ang = float(np_module.degrees(np_module.arctan2(dy, dx)))
            while ang > 90.0:
                ang -= 180.0
            while ang < -90.0:
                ang += 180.0
            if abs(ang) <= 35.0:
                angles.append(ang)
    plate_angle = float(np_module.median(angles)) if angles else 0.0

    rotated, mat = _rotate_image_keep_size(img, -plate_angle)
    if mat is None:
        return None, plate_angle

    rgray = cv2.cvtColor(rotated, cv2.COLOR_BGR2GRAY)
    rgray = cv2.bilateralFilter(rgray, 7, 50, 50)
    redges = cv2.Canny(rgray, 80, 180)
    contours, _ = cv2.findContours(redges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    best_box = None
    best_score = -1.0
    frame_area = float(h * w)
    for c in contours:
        area = float(cv2.contourArea(c))
        if area < frame_area * 0.001 or area > frame_area * 0.30:
            continue
        rect = cv2.minAreaRect(c)
        (_, _), (rw, rh), _ = rect
        if rw <= 1.0 or rh <= 1.0:
            continue
        ww = max(float(rw), float(rh))
        hh = min(float(rw), float(rh))
        ratio = ww / max(hh, 1e-6)
        if ratio < 2.0 or ratio > 6.8:
            continue
        rect_area = ww * hh
        solidity = area / max(rect_area, 1.0)
        if solidity < 0.35:
            continue
        ratio_score = 1.0 / (1.0 + abs(ratio - 4.0))
        area_score = min(rect_area / (frame_area * 0.03), 1.0)
        score = 0.7 * ratio_score + 0.3 * area_score
        if score > best_score:
            best_score = score
            best_box = cv2.boxPoints(rect)

    if best_box is None:
        return None, plate_angle

    inv_mat = cv2.invertAffineTransform(mat)
    pts = np_module.asarray(best_box, dtype=np_module.float32)
    ones = np_module.ones((pts.shape[0], 1), dtype=np_module.float32)
    pts_h = np_module.hstack((pts, ones))
    mapped = pts_h @ inv_mat.T
    xs = mapped[:, 0]
    ys = mapped[:, 1]
    x1 = int(max(0, min(xs)))
    y1 = int(max(0, min(ys)))
    x2 = int(min(w, max(xs)))
    y2 = int(min(h, max(ys)))
    if x2 <= x1 or y2 <= y1:
        return None, plate_angle
    return (x1, y1, x2, y2), plate_angle


def _read_onnx_input_hw():
    # Try common attribute locations used by wrappers around onnxruntime.
    candidates = []
    for attr in ("session", "_session", "ort_session", "_ort_session"):
        sess = getattr(ocr_recognizer, attr, None)
        if sess is not None:
            candidates.append(sess)
    model_obj = getattr(ocr_recognizer, "model", None)
    if model_obj is not None:
        for attr in ("session", "_session", "ort_session", "_ort_session"):
            sess = getattr(model_obj, attr, None)
            if sess is not None:
                candidates.append(sess)

    for sess in candidates:
        try:
            shape = sess.get_inputs()[0].shape
            if len(shape) == 4:
                # NCHW expected in this model family.
                h = int(shape[2]) if isinstance(shape[2], (int, float)) else 0
                w = int(shape[3]) if isinstance(shape[3], (int, float)) else 0
                if h > 0 and w > 0:
                    return (w, h)
        except Exception:
            continue
    return None


def prepare_ocr_input(img):
    if img is None:
        return None

    try:
        import cv2
    except Exception:
        cv2 = None

    work = img
    if work.ndim == 2:
        if cv2 is not None:
            work = cv2.cvtColor(work, cv2.COLOR_GRAY2BGR)
        else:
            work = np_module.stack((work, work, work), axis=-1)

    target = _read_onnx_input_hw()
    if target and cv2 is not None:
        tw, th = target
        if work.shape[1] != tw or work.shape[0] != th:
            work = cv2.resize(work, (tw, th), interpolation=cv2.INTER_AREA)

    # Recognizer typically expects RGB input.
    if cv2 is not None:
        work = cv2.cvtColor(work, cv2.COLOR_BGR2RGB)
    else:
        work = work[:, :, ::-1]

    return np_module.ascontiguousarray(work)


def mean_conf(values):
    if values is None:
        return 0.0
    try:
        vals = list(values)
        if not vals:
            return 0.0
        return float(sum(float(v) for v in vals) / len(vals))
    except Exception:
        return 0.0


def parse_ocr_result(result):
    # Newer API may return a list of prediction objects (with .plate/.char_probs)
    # Older API may return (plates, confidences)
    plate = ""
    conf = 0.0

    if isinstance(result, tuple) and len(result) == 2:
        plates, confidences = result
        if isinstance(plates, list) and plates:
            plate = str(plates[0])
        conf0 = None
        try:
            conf0 = confidences[0]
        except Exception:
            conf0 = confidences
        conf = mean_conf(conf0)
        return plate, conf

    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, str):
            return first, 0.0
        if hasattr(first, "plate"):
            plate = str(getattr(first, "plate", ""))
            conf = mean_conf(getattr(first, "char_probs", None))
            return plate, conf
        if isinstance(first, dict):
            plate = str(first.get("plate", ""))
            conf = mean_conf(first.get("char_probs"))
            return plate, conf
        return str(first), 0.0

    if isinstance(result, str):
        return result, 0.0

    return "", 0.0


def normalize_plate_text(plate):
    if not plate:
        return ""
    # Keep only alphanumeric characters and uppercase for stable matching.
    return "".join(ch for ch in str(plate).upper() if ch.isalnum())


def is_plate_allowed_for_country(plate):
    if OCR_COUNTRY == "US":
        return bool(US_PLATE_RE.match(plate))
    return True


def _read_pi_temp_c():
    try:
        proc = subprocess.run(
            ["vcgencmd", "measure_temp"],
            capture_output=True,
            text=True,
            check=False,
        )
        out = (proc.stdout or "").strip()
        # Expected: temp=54.8'C
        if "temp=" in out and "'" in out:
            value = out.split("temp=", 1)[1].split("'", 1)[0]
            return float(value)
    except Exception:
        pass
    return None


def _dm_to_decimal(dm_text, hemisphere):
    if not dm_text:
        return None
    try:
        dm = float(dm_text)
    except Exception:
        return None
    degrees = int(dm // 100)
    minutes = dm - (degrees * 100)
    dec = degrees + (minutes / 60.0)
    if hemisphere in ("S", "W"):
        dec = -dec
    return dec


def _parse_cgpsinfo(payload):
    # +CGPSINFO: <lat>,<N/S>,<lon>,<E/W>,<date>,<utc>,<alt>,<speed>,<course>
    parts = [p.strip() for p in payload.split(",")]
    if len(parts) < 9:
        return None
    lat = _dm_to_decimal(parts[0], parts[1] if len(parts) > 1 else "")
    lon = _dm_to_decimal(parts[2], parts[3] if len(parts) > 3 else "")
    if lat is None or lon is None:
        return None
    speed = 0.0
    course = 0.0
    try:
        speed = float(parts[7]) if parts[7] else 0.0
    except Exception:
        speed = 0.0
    try:
        course = float(parts[8]) if parts[8] else 0.0
    except Exception:
        course = 0.0
    utc = ""
    if len(parts) > 5 and parts[5]:
        utc = parts[5]
    return {
        "gps_status": "ok",
        "gps_lat": lat,
        "gps_lon": lon,
        "gps_speed_knots": speed,
        "gps_course_deg": course,
        "gps_utc": utc,
    }


def _parse_cgnssinfo(payload):
    # SIM7600 common: +CGNSSINFO: <mode>,<sats>,<lat>,<N/S>,<lon>,<E/W>,<date>,<utc>,...
    parts = [p.strip() for p in payload.split(",")]
    if len(parts) < 8:
        return None
    lat = _dm_to_decimal(parts[2], parts[3] if len(parts) > 3 else "")
    lon = _dm_to_decimal(parts[4], parts[5] if len(parts) > 5 else "")
    if lat is None or lon is None:
        return None
    sats_used = 0
    speed = 0.0
    course = 0.0
    try:
        sats_used = int(parts[1]) if parts[1] else 0
    except Exception:
        sats_used = 0
    if len(parts) > 12:
        try:
            speed = float(parts[12]) if parts[12] else 0.0
        except Exception:
            speed = 0.0
    if len(parts) > 13:
        try:
            course = float(parts[13]) if parts[13] else 0.0
        except Exception:
            course = 0.0
    utc = parts[7] if len(parts) > 7 else ""
    return {
        "gps_status": "ok",
        "gps_lat": lat,
        "gps_lon": lon,
        "gps_speed_knots": speed,
        "gps_course_deg": course,
        "gps_utc": utc,
        "gps_sats_used": sats_used,
    }


def _at_query(ser, command):
    ser.reset_input_buffer()
    ser.write((command + "\r\n").encode("ascii"))
    ser.flush()
    time.sleep(0.2)
    raw = ser.read(4096).decode("ascii", errors="ignore")
    return raw


def gps_worker():
    if not GPS_ENABLE:
        set_gps_state(gps_status="disabled")
        return
    try:
        import serial
    except Exception as exc:
        set_gps_state(gps_status=f"error:pyserial ({exc})")
        return

    while not ocr_stop.is_set():
        ser = None
        try:
            set_gps_state(gps_status="connecting")
            ser = serial.Serial(GPS_PORT, GPS_BAUD, timeout=1.0)
            _at_query(ser, "AT")
            # Turn GNSS on (idempotent for SIM7600 modules).
            _at_query(ser, "AT+CGPS=1")
            set_gps_state(gps_status="searching")

            while not ocr_stop.is_set():
                out = _at_query(ser, "AT+CGNSSINFO")
                payload = None
                for ln in out.splitlines():
                    ln = ln.strip()
                    if ln.startswith("+CGNSSINFO:"):
                        payload = ln.split(":", 1)[1].strip()
                        break
                parsed = _parse_cgnssinfo(payload) if payload else None
                if not parsed:
                    out2 = _at_query(ser, "AT+CGPSINFO")
                    payload2 = None
                    for ln in out2.splitlines():
                        ln = ln.strip()
                        if ln.startswith("+CGPSINFO:"):
                            payload2 = ln.split(":", 1)[1].strip()
                            break
                    parsed = _parse_cgpsinfo(payload2) if payload2 else None

                if parsed:
                    set_gps_state(**parsed)
                else:
                    set_gps_state(gps_status="searching")
                ocr_stop.wait(max(0.2, GPS_INTERVAL_SEC))
        except Exception as exc:
            set_gps_state(gps_status=f"error:{exc}")
            ocr_stop.wait(2.0)
        finally:
            if ser is not None:
                try:
                    _at_query(ser, "AT+CGPS=0")
                except Exception:
                    pass
                try:
                    ser.close()
                except Exception:
                    pass


def _compute_thermal_profile(temp_c):
    if temp_c is None:
        return ("unknown", 1.0, False, "no_sensor")
    if temp_c >= TEMP_CRIT_C:
        return ("critical", 1e9, True, "critical_pause_ocr")
    if temp_c >= TEMP_HOT_C:
        return ("hot", 6.0, False, "hot_slow_ocr")
    if temp_c >= TEMP_WARN_C:
        return ("warm", 2.5, False, "warm_slow_ocr")
    return ("normal", 1.0, False, "normal")


def thermal_worker():
    last_zone = None
    while not ocr_stop.is_set():
        temp_c = _read_pi_temp_c()
        zone, scale, paused, status = _compute_thermal_profile(temp_c)
        with thermal_lock:
            thermal_state["temp_c"] = float(temp_c or 0.0)
            thermal_state["zone"] = zone
            thermal_state["ocr_scale"] = float(scale)
            thermal_state["ocr_paused"] = bool(paused)
            thermal_state["status"] = status
        if zone != last_zone:
            logging.info(
                "thermal zone=%s temp=%.1fC ocr_scale=%.2f paused=%s",
                zone,
                float(temp_c or 0.0),
                float(scale),
                str(paused),
            )
            last_zone = zone
        ocr_stop.wait(1.0)


def ocr_worker():
    next_run = time.monotonic()
    while not ocr_stop.is_set():
        if ocr_recognizer is None:
            ocr_stop.wait(1.0)
            continue

        now = time.monotonic()
        if now < next_run:
            ocr_stop.wait(next_run - now)
            continue
        with thermal_lock:
            paused = bool(thermal_state.get("ocr_paused", False))
            scale = float(thermal_state.get("ocr_scale", 1.0))
        effective_interval = max(0.1, OCR_INTERVAL_SEC * max(1.0, scale))
        next_run = now + effective_interval

        if paused:
            set_ocr_state(status=f"thermal-paused:{thermal_state.get('zone', 'unknown')}")
            continue

        frame = None
        with output.condition:
            frame = output.frame

        if not frame:
            continue

        img = decode_jpeg_to_bgr(frame)
        if img is None:
            set_ocr_state(status="error:decode")
            continue

        ih, iw = img.shape[:2]
        bbox, plate_angle = _detect_plate_bbox_hough(img)
        plate_detected = bbox is not None
        if not plate_detected:
            set_ocr_state(
                status="no_plate",
                plate="",
                confidence=0.0,
                latency_ms=0.0,
                plate_detected=False,
                plate_angle_deg=0.0,
                plate_bbox_norm=[],
            )
            continue

        x1, y1, x2, y2 = bbox
        crop = img[y1:y2, x1:x2]
        if crop is None or crop.size == 0:
            set_ocr_state(
                status="error:crop",
                plate_detected=False,
                plate_angle_deg=0.0,
                plate_bbox_norm=[],
            )
            continue

        if abs(plate_angle) > 1.0:
            crop, _ = _rotate_image_keep_size(crop, -plate_angle)

        ocr_input = prepare_ocr_input(crop)
        if ocr_input is None:
            set_ocr_state(
                status="error:decode",
                plate_detected=plate_detected,
                plate_angle_deg=plate_angle,
                plate_bbox_norm=bbox_to_norm(bbox, iw, ih),
            )
            continue

        try:
            t0 = time.perf_counter()
            result = ocr_recognizer.run(ocr_input, return_confidence=True)
            latency_ms = (time.perf_counter() - t0) * 1000.0
            plate, conf = parse_ocr_result(result)
            plate = normalize_plate_text(plate)
            if not is_plate_allowed_for_country(plate):
                plate = ""
            model_tag = ocr_model_in_use or OCR_MODEL
            set_ocr_state(
                status=f"ready:{ocr_backend}:{model_tag}",
                plate=plate,
                confidence=conf,
                latency_ms=latency_ms,
                plate_detected=plate_detected,
                plate_angle_deg=plate_angle,
                plate_bbox_norm=bbox_to_norm(bbox, iw, ih),
            )
        except Exception as exc:
            set_ocr_state(
                status=f"error:{exc}",
                plate_detected=plate_detected,
                plate_angle_deg=plate_angle,
                plate_bbox_norm=bbox_to_norm(bbox, iw, ih),
            )


def _camera_holders():
    cmd = ["fuser", "-v", "/dev/video0", "/dev/media0", "/dev/media1", "/dev/media2"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        out = (proc.stdout or "") + (proc.stderr or "")
        return out.strip()
    except Exception:
        return ""


def create_camera_with_retry(retries=8, delay_sec=1.0):
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            cam = Picamera2()
            return cam
        except Exception as exc:
            last_exc = exc
            logging.warning("Camera busy (attempt %d/%d): %s", attempt, retries, exc)
            if attempt < retries:
                time.sleep(delay_sec)
    holders = _camera_holders()
    if holders:
        logging.error("Camera device holders:\n%s", holders)
    raise RuntimeError(
        "Failed to acquire camera after retries. Another process likely holds it."
    ) from last_exc


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

picam2 = create_camera_with_retry()
picam2.configure(picam2.create_video_configuration(main={"size": (1440, 1080)}))
output = StreamingOutput()
picam2.start_recording(MJPEGEncoder(bitrate=90000000), FileOutput(output))
apply_camera_profile("normal")
init_ocr()
ocr_thread = Thread(target=ocr_worker, daemon=True)
ocr_thread.start()
thermal_thread = Thread(target=thermal_worker, daemon=True)
thermal_thread.start()
gps_thread = Thread(target=gps_worker, daemon=True)
gps_thread.start()

address = ('', 8000)
httpd = StreamingServer(address, StreamingHandler)
shutdown_requested = False


def _request_shutdown(signum, _frame):
    global shutdown_requested
    if shutdown_requested:
        return
    shutdown_requested = True
    logging.info("Received signal %s, shutting down...", signum)
    # shutdown() must run from a different thread than serve_forever.
    Thread(target=httpd.shutdown, daemon=True).start()


signal.signal(signal.SIGINT, _request_shutdown)
signal.signal(signal.SIGTERM, _request_shutdown)

try:
    httpd.serve_forever()
except KeyboardInterrupt:
    logging.info("KeyboardInterrupt received, shutting down...")
finally:
    try:
        httpd.shutdown()
    except Exception:
        pass
    httpd.server_close()
    ocr_stop.set()
    try:
        ocr_thread.join(timeout=2.0)
    except Exception:
        pass
    try:
        thermal_thread.join(timeout=2.0)
    except Exception:
        pass
    try:
        gps_thread.join(timeout=2.0)
    except Exception:
        pass
    picam2.stop_recording()
