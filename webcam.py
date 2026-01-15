
import os, sys, time, signal, subprocess, logging, threading
from urllib.request import Request, urlopen

STREAM_URL = os.environ.get("STREAM_URL")
OUTDIR = os.environ.get("OUTDIR", "/data/images")
INTERVAL = int(os.environ.get("INTERVAL", "20"))
RESTART_WINDOW = int(os.environ.get("RESTART_WINDOW", "60"))
RESTART_LIMIT = int(os.environ.get("RESTART_LIMIT", "10"))
MAX_RESTART_DELAY = int(os.environ.get("MAX_RESTART_DELAY", "300"))
UNRESPONSIVE_THRESHOLD_MULTIPLIER = int(os.environ.get("UNRESPONSIVE_THRESHOLD_MULTIPLIER", "6"))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
WEBHOOK_PAYLOAD = os.environ.get("WEBHOOK_PAYLOAD", "")
QUALITY = os.environ.get("QUALITY", "2")
STARTUP_GRACE_PERIOD=INTERVAL*4

if not STREAM_URL:
    print("ERROR: STREAM_URL must be set", file=sys.stderr)
    sys.exit(2)

os.makedirs(OUTDIR, exist_ok=True)

lastStart = time.time()
consecutiveRestarts = 0

child = None
terminate = False

unresponsiveThreshold = UNRESPONSIVE_THRESHOLD_MULTIPLIER * INTERVAL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

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

def last_image_age():
    try:
        files = [os.path.join(OUTDIR, f) for f in os.listdir(OUTDIR)]
        files = [f for f in files if os.path.isfile(f)]
        if not files:
            return None
        return time.time() - max(os.path.getmtime(f) for f in files)
    except Exception:
        return None

def stream_process_output(proc, logger):
    def _reader(pipe):
        try:
            for line in iter(pipe.readline, ''):
                if not line:
                    break
                logger.info(line.rstrip())
        except Exception as e:
            logger.exception("Error reading subprocess output: %s", e)
    t = threading.Thread(target=_reader, args=(proc.stdout,), daemon=True)
    t.start()
    return t

def start_ffmpeg():
    cmd = [
        "ffmpeg", "-loglevel", "info",
        "-i", STREAM_URL,
        "-vf", f"fps=1/{INTERVAL}",
        "-q:v", QUALITY,
        "-strftime", "1",
        os.path.join(OUTDIR, "photo_%Y%m%d_%H%M%S.jpg")
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        universal_newlines=True
    )
    stream_process_output(proc, logging)
    return proc

while True:
    if terminate:
        logging.info("Terminate flag set — exiting main loop")
        break
    lastStart = time.time()
    child = start_ffmpeg()

    rc = None
    check_sleep = 2
    while True:
        rc = child.poll()
        if rc is not None:            # ffmpeg is terminated
            logging.warning("ffmpeg exited with returncode=%s", rc)
            break

        if terminate:                 # Signal received
            logging.info("Termination requested — stopping child")
            try:
                child.terminate()
                time.sleep(2)
                if child.poll() is None:
                    child.kill()
            except Exception:
                logging.exception("Error while terminating child")
            break

        age = last_image_age()
        if age is None:
            logging.debug("No images yet in OUTDIR (%s)", OUTDIR)
        else:
            logging.debug("Last image age: %.1f s", age)


        if age is not None and age > unresponsiveThreshold and time.time() > lastStart + STARTUP_GRACE_PERIOD:
            # ffmpeg does no yield new images
            logging.warning("No new images for %.1f s (threshold %s) — restarting ffmpeg", age, unresponsiveThreshold)
            try:
                child.terminate()
                time.sleep(2)
                if child.poll() is None:
                    child.kill()
            except Exception:
                logging.exception("Error while killing unresponsive child")
            break

        time.sleep(check_sleep)

    now = time.time()
    if now - lastStart > RESTART_WINDOW:
        logging.info("Stable run (%.1fs) — reset consecutiveRestarts", now - lastStart)
        consecutiveRestarts = 0
    else:
        consecutiveRestarts += 1
        logging.info("ffmpeg restarted quickly — consecutiveRestarts=%d", consecutiveRestarts)

    if consecutiveRestarts >= RESTART_LIMIT:
        logging.error("Reached RESTART_LIMIT (%d). Sending webhook and exiting.", RESTART_LIMIT)
        msg = WEBHOOK_PAYLOAD
        notify_webhook(WEBHOOK_URL, msg)
        sys.exit(0)

    delay = min((1.75 ** consecutiveRestarts), MAX_RESTART_DELAY)

    logging.info("Sleeping %.1f s before next start", delay)
    end_time = time.time() + delay
    while time.time() < end_time:
        if terminate:
            break
        time.sleep(0.2)

sys.exit(0)
