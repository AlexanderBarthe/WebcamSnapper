
import os, sys, time, signal, subprocess, logging, threading
from urllib.request import Request, urlopen

def get_env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (ValueError, TypeError):
        return default


STREAM_URL = os.environ.get("STREAM_URL")
OUTDIR = os.environ.get("OUTDIR", "/data/images")
INTERVAL = get_env_int("INTERVAL", "20")
QUALITY = os.environ.get("QUALITY", "2")

WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
WEBHOOK_TERM_MSG = os.environ.get("WEBHOOK_TERM_MSG", "")
WEBHOOK_WARN_MSG=os.environ.get("WEBHOOK_WARN_MSG", "")
WEBHOOK_RECOV_MSG=os.environ.get("WEBHOOK_RECOV_MSG", "")

RESTART_WARN_THRESHOLD=get_env_int("RESTART_WARN_THRESHOLD", "10")
RESTART_LIMIT = get_env_int("RESTART_LIMIT", "200")

MAX_RESTART_DELAY = get_env_int("MAX_RESTART_DELAY", "300")
PROC_HEALTHY_START_MULTIPLIER = get_env_int("PROC_HEALTHY_STARTUP_MULTIPLIER", "4")
PROC_HEALTHY_START_THRESHOLD = INTERVAL * PROC_HEALTHY_START_MULTIPLIER
PROC_UNRESPONSIVE_MULTIPLIER = get_env_int("PROC_UNRESPONSIVE_MULTIPLIER", "6")
PROC_UNRESPONSIVE_THRESHOLD = INTERVAL * PROC_UNRESPONSIVE_MULTIPLIER

if not STREAM_URL:
    print("ERROR: STREAM_URL must be set", file=sys.stderr)
    sys.exit(2)

os.makedirs(OUTDIR, exist_ok=True)

lastStart = time.time()
consecutiveFailures = 0

child = None
terminate = False

logger = logging.getLogger("webcam_snapper")
logger.setLevel(logging.INFO)

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(handler)


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
    except Exception as e:
        print(e)


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


def last_image_age():
    try:
        files = [os.path.join(OUTDIR, f) for f in os.listdir(OUTDIR)]
        files = [f for f in files if os.path.isfile(f)]
        if not files:
            return None
        return time.time() - max(os.path.getmtime(f) for f in files)
    except Exception:
        return None


def stream_process_output(proc):
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
    stream_process_output(proc)
    return proc


def process_healthy():

    # Check termination
    rc = child.poll()
    if rc is not None:
        logger.warning("ffmpeg exited with returncode=%s", rc)
        return False

    # Check for unresponsiveness
    age = last_image_age()
    if age is None:
        logger.debug("No images yet in OUTDIR (%s)", OUTDIR)
    else:
        logger.debug("Last image age: %.1f s", age)

    if age is not None and age > PROC_UNRESPONSIVE_THRESHOLD and time.time() > lastStart + PROC_HEALTHY_START_THRESHOLD:
        logger.warning("No new images for %.1f s (threshold %s)", age, PROC_UNRESPONSIVE_THRESHOLD)
        return False

    return True


signal.signal(signal.SIGTERM, sigterm_handler)
signal.signal(signal.SIGINT, sigterm_handler)

while True:

    lastStart = time.time()
    child = start_ffmpeg()

    # while process healthy
    while True:

        # Stop if terminated
        if terminate:
            logger.info("Termination requested - stopping")
            try:
                child.terminate()
                time.sleep(2)
                if child.poll() is None:
                    child.kill()
            except Exception:
                logger.exception("Error while terminating child")
            break

        # Stop if unhealthy
        if not process_healthy():
            try:
                child.terminate()
                time.sleep(2)
                if child.poll() is None:
                    child.kill()
            except Exception:
                logger.exception("Error while killing unresponsive child")
            break

        # Reset consecutive failures
        if time.time() > lastStart + PROC_HEALTHY_START_THRESHOLD:
            if consecutiveFailures >= RESTART_WARN_THRESHOLD:
                # Recovered from failure
                msg = WEBHOOK_RECOV_MSG
                notify_webhook(WEBHOOK_URL, msg)

            consecutiveFailures = 0

        time.sleep(1)

    if terminate:
        break

    consecutiveFailures += 1
    logger.warning("ffmpeg failed. Consecutive failures: %d", consecutiveFailures)

    if consecutiveFailures == RESTART_WARN_THRESHOLD:
        logger.info("Notifying webhook about issues")
        msg = WEBHOOK_WARN_MSG
        notify_webhook(WEBHOOK_URL, msg)

    if consecutiveFailures >= RESTART_LIMIT:
        logger.error("Reached RESTART_LIMIT (%d). Sending webhook and exiting.", RESTART_LIMIT)
        msg = WEBHOOK_TERM_MSG
        notify_webhook(WEBHOOK_URL, msg)
        sys.exit(0)

    # Delaying next start
    delay = min((1.75 ** consecutiveFailures), MAX_RESTART_DELAY)

    logger.warning("Sleeping %.1f s before next start", delay)
    end_time = time.time() + delay
    while time.time() < end_time:
        if terminate:
            break
        time.sleep(0.2)

sys.exit(0)
