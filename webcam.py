
import os, sys, time, signal, subprocess
from urllib.request import Request, urlopen

STREAM_URL = os.environ.get("STREAM_URL")
OUTDIR = os.environ.get("OUTDIR", "/data/images")
INTERVAL = int(os.environ.get("INTERVAL", "20"))
RESTART_WINDOW = int(os.environ.get("RESTART_WINDOW", "60"))
RESTART_LIMIT = int(os.environ.get("RESTART_LIMIT", "10"))
MAX_RESTART_DELAY = int(os.environ.get("MAX_RESTART_DELAY", "300"))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
WEBHOOK_PAYLOAD = os.environ.get("WEBHOOK_PAYLOAD", "")
QUALITY = os.environ.get("QUALITY", "2")

if not STREAM_URL:
    print("ERROR: STREAM_URL must be set", file=sys.stderr)
    sys.exit(2)

os.makedirs(OUTDIR, exist_ok=True)

lastStart = time.time()
consecutiveRestarts = 0

child = None
terminate = False

def notify_webhook(webhook_url, payload):
    if not webhook_url:
        return
    if not payload.startswith("{"):
        payload = "{" + payload
    if not payload.endswith("}"):
        payload += "}"

    payload = payload.encode("utf-8")

    req = Request(webhook_url,
                  data=payload,
                  headers={"Content-Type": "application/json",
                            "User-Agent": "webcam-snapper/1.0"})
    try:
        urlopen(req, timeout=5)
    except Exception:
        pass

# handle termination
def sigterm_handler(signum, frame):
    global terminate, child
    terminate = True
    if child and child.poll() is None:
        try:
            child.terminate()
            time.sleep(2)
            if child.poll() is None:
                child.kill()
        except Exception:
            pass

signal.signal(signal.SIGTERM, sigterm_handler)
signal.signal(signal.SIGINT, sigterm_handler)

def start_ffmpeg():
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-i", STREAM_URL,
        "-vf", f"fps=1/{INTERVAL}",
        "-q:v", QUALITY,
        "-strftime", "1",
        os.path.join(OUTDIR, "photo_%Y%m%d_%H%M%S.jpg")
    ]
    return subprocess.Popen(cmd)

while True:
    if terminate:
        break
    lastStart = time.time()
    child = start_ffmpeg()
    try:
        rc = child.wait()
    except Exception:
        rc = child.poll()

    now = time.time()
    if now - lastStart > RESTART_WINDOW:
        consecutiveRestarts = 0
    else:
        consecutiveRestarts += 1

    if consecutiveRestarts >= RESTART_LIMIT:
        msg = WEBHOOK_PAYLOAD
        notify_webhook(WEBHOOK_URL, msg)
        sys.exit(0)

    delay = min((1.75 ** consecutiveRestarts), MAX_RESTART_DELAY)

    end_time = time.time() + delay
    while time.time() < end_time:
        if terminate:
            break
        time.sleep(0.2)

sys.exit(0)
