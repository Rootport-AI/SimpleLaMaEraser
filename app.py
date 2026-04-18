import io
import os
import sys
import threading
import time
import uuid

import numpy as np
import torch
import torchvision
from flask import Flask, Response, jsonify, render_template, request, send_from_directory
from omegaconf import OmegaConf
from PIL import Image
from saicinpainting.training.trainers import load_checkpoint
import logging

# ============================================================
# Configuration
# ============================================================

MAX_UPLOAD_MB = 64

# Access control:
#   False = localhost only (127.0.0.1, ::1)
#   True  = allow connections from LAN as well
# In the future this will be configurable from the GUI settings screen.
ALLOW_LAN_ACCESS = False

_LOCALHOST_ADDRS = {'127.0.0.1', '::1', '::ffff:127.0.0.1'}

CROP_MARGIN = 128    # pixels added around the mask bbox on each side

# ============================================================
# Logging
# ============================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# Startup initialization
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Set environment variables once at startup, not inside request handlers.
os.environ['TORCH_HOME'] = BASE_DIR
os.environ['PYTHONPATH'] = BASE_DIR

# Detect CUDA availability. Unlike the previous version, absence of CUDA is not
# a fatal error — the tool can run in CPU mode, just significantly slower.
CUDA_AVAILABLE = torch.cuda.is_available()
if not CUDA_AVAILABLE:
    logger.warning("CUDA is not available. Starting in CPU mode.")

# Default device: GPU if available, CPU otherwise.
# Can be changed at runtime via POST /set_mode.
DEVICE = 'cuda' if CUDA_AVAILABLE else 'cpu'

# Crop mode: default ON when starting in CPU mode to keep inference time manageable.
CROP_MODE = not CUDA_AVAILABLE

# ============================================================
# Model management
# ============================================================

MODEL_PATH = os.path.join(BASE_DIR, 'big-lama')
MODEL = None
_MODEL_LOAD_LOCK = threading.Lock()


def load_model():
    """Load the LaMa model to the current DEVICE. Idempotent and thread-safe."""
    global MODEL
    with _MODEL_LOAD_LOCK:
        if MODEL is not None:
            return
        logger.info(f"Model load started | path={MODEL_PATH}")
        import yaml
        config_path = os.path.join(MODEL_PATH, 'config.yaml')
        checkpoint_path = os.path.join(MODEL_PATH, 'models', 'best.ckpt')
        with open(config_path, 'r') as f:
            train_config = OmegaConf.create(yaml.safe_load(f))
        train_config.training_model.predict_only = True
        train_config.visualizer.kind = 'noop'
        # Weights are always loaded to CPU first, then moved to DEVICE.
        # This avoids a CUDA OOM during checkpoint deserialization.
        MODEL = load_checkpoint(train_config, checkpoint_path, strict=False, map_location='cpu')
        MODEL.freeze()
        MODEL.to(DEVICE)
        logger.info(f"Model load complete | device={DEVICE}")
        logger.info(f"ResNetPL in model: {'loss_resnet_pl' in dir(MODEL)}")

# ============================================================
# Flask application
# ============================================================

app = Flask(__name__)
app.config['OUTPUT_FOLDER'] = os.path.join(BASE_DIR, 'output')
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_MB * 1024 * 1024

os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

# Shared lock for both inference jobs and device switching.
# /process acquires it non-blocking (→ 409 if busy).
# /set_mode acquires it blocking with timeout (waits for any running job to finish).
_PROCESS_LOCK = threading.Lock()

# ============================================================
# Access control
# ============================================================

@app.before_request
def enforce_access_control():
    """Block non-localhost requests unless LAN access is explicitly enabled."""
    if ALLOW_LAN_ACCESS:
        return
    if request.remote_addr not in _LOCALHOST_ADDRS:
        logger.warning(f"Access denied from {request.remote_addr}")
        return jsonify({
            'error': 'forbidden',
            'message': 'Access from this address is not allowed.'
        }), 403

# ============================================================
# Error handlers
# ============================================================

@app.errorhandler(413)
def request_entity_too_large(e):
    return jsonify({
        'error': 'payload_too_large',
        'message': f'Upload size exceeds the {MAX_UPLOAD_MB}MB limit.'
    }), 413

# ============================================================
# Custom exception
# ============================================================

class ProcessingError(Exception):
    """Carries a machine-readable error code and a human-readable message."""
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)

# ============================================================
# Validation layer
# ============================================================

def validate_inputs(image_file, mask_file):
    """
    Decode and validate uploaded image and mask files.

    Returns:
        pil_image (PIL.Image, mode=RGBA)
        mask_arr  (np.ndarray, uint8, shape H×W, values 0 or 255 only)
    Raises:
        ProcessingError on any validation failure.
    """
    # --- Decode image ---
    try:
        pil_image = Image.open(image_file)
        pil_image.load()  # force full decode before stream may close
    except Exception as e:
        raise ProcessingError('invalid_image_mode', f'Cannot decode image file: {e}')

    if pil_image.mode == 'RGB':
        pil_image = pil_image.convert('RGBA')
    elif pil_image.mode != 'RGBA':
        raise ProcessingError(
            'invalid_image_mode',
            f'Image must be RGBA (or RGB). Received mode: {pil_image.mode}'
        )

    # --- Decode mask ---
    try:
        pil_mask = Image.open(mask_file)
        pil_mask.load()
    except Exception as e:
        raise ProcessingError('invalid_mask_mode', f'Cannot decode mask file: {e}')

    if pil_mask.mode != 'L':
        if pil_mask.mode in ('RGB', 'RGBA', 'P', '1', 'LA'):
            pil_mask = pil_mask.convert('L')
        else:
            raise ProcessingError(
                'invalid_mask_mode',
                f'Mask must be grayscale (L). Received mode: {pil_mask.mode}'
            )

    # --- Size consistency ---
    if pil_image.size != pil_mask.size:
        raise ProcessingError(
            'size_mismatch',
            f'Image size {pil_image.size} does not match mask size {pil_mask.size}.'
        )

    # Binarize the mask: >= 128 → 255 (erase), < 128 → 0 (keep).
    # Clients are expected to send a pre-binarized mask, but this threshold
    # conversion handles minor compression artifacts gracefully.
    mask_arr = np.array(pil_mask, dtype=np.uint8)
    mask_arr = np.where(mask_arr >= 128, np.uint8(255), np.uint8(0))

    return pil_image, mask_arr

# ============================================================
# Image processing layer
# ============================================================

def pad_to_multiple(arr: np.ndarray, multiple: int = 8, mode: str = 'reflect') -> np.ndarray:
    """Right/bottom pad so H and W are multiples of `multiple`."""
    h, w = arr.shape[:2]
    pad_h = (multiple - h % multiple) % multiple
    pad_w = (multiple - w % multiple) % multiple
    if pad_h == 0 and pad_w == 0:
        return arr
    if arr.ndim == 3:
        return np.pad(arr, ((0, pad_h), (0, pad_w), (0, 0)), mode=mode)
    return np.pad(arr, ((0, pad_h), (0, pad_w)), mode=mode)


def get_mask_bbox(mask_arr: np.ndarray):
    """
    Return the bounding box of non-zero pixels as (x_min, y_min, x_max, y_max).
    x_max and y_max are exclusive (numpy-slice compatible).
    Returns None if the mask contains no 255-valued pixels.
    """
    rows = np.any(mask_arr == 255, axis=1)
    cols = np.any(mask_arr == 255, axis=0)
    if not rows.any():
        return None
    y_min, y_max = int(np.where(rows)[0][0]),  int(np.where(rows)[0][-1])
    x_min, x_max = int(np.where(cols)[0][0]),  int(np.where(cols)[0][-1])
    return (x_min, y_min, x_max + 1, y_max + 1)


def expand_crop_box(bbox, margin: int, img_w: int, img_h: int):
    """
    Expand a bounding box by `margin` pixels on each side with smart edge
    compensation (IOPaint-style): if the expanded box goes past one boundary,
    the opposite side is extended to preserve total context area.

    Returns: (l, t, r, b) clamped to [0, img_w] × [0, img_h].
    """
    x_min, y_min, x_max, y_max = bbox
    cx = (x_min + x_max) // 2
    cy = (y_min + y_max) // 2

    w = (x_max - x_min) + margin * 2
    h = (y_max - y_min) + margin * 2

    l = cx - w // 2
    r = cx + w // 2
    t = cy - h // 2
    b = cy + h // 2

    # If the box overshoots one edge, push the opposite side outward
    # so the total crop area (and thus LaMa's context) stays the same.
    if l < 0:      r += abs(l)
    if r > img_w:  l -= (r - img_w)
    if t < 0:      b += abs(t)
    if b > img_h:  t -= (b - img_h)

    # Final clamp to image boundaries
    l = max(l, 0)
    r = min(r, img_w)
    t = max(t, 0)
    b = min(b, img_h)

    return (l, t, r, b)


def run_lama_inference(rgb_float: np.ndarray, mask_arr: np.ndarray, request_id: str) -> np.ndarray:
    """
    Run LaMa inference on an RGB image with a binary mask.

    Args:
        rgb_float:  float32 ndarray [H, W, 3] in range [0, 1]
        mask_arr:   uint8  ndarray [H, W]     values 0 or 255
        request_id: used for log correlation

    Returns:
        float32 ndarray [H, W, 3] in range [0, 1], cropped back to original H×W

    Raises:
        ProcessingError if the crop-back size check fails.
        Other exceptions (e.g. CUDA OOM) bubble up to the caller.
    """
    orig_h, orig_w = rgb_float.shape[:2]

    # Pad to nearest multiple of 8 (LaMa internal requirement).
    # Use reflect for RGB (avoids colour discontinuities at border).
    # Use constant=0 for mask (do not request inpainting in the padded margin).
    rgb_padded  = pad_to_multiple(rgb_float, 8, mode='reflect')   # [H', W', 3]
    mask_padded = pad_to_multiple(mask_arr,  8, mode='constant')  # [H', W']

    # Snapshot the current device. DEVICE may change between requests, but
    # _PROCESS_LOCK guarantees it stays constant for the duration of this call.
    device = DEVICE

    # Build batch tensors [1, C, H', W'] on the active device
    img_tensor = (
        torch.from_numpy(rgb_padded.transpose(2, 0, 1))
        .unsqueeze(0).float().to(device)
    )
    mask_tensor = (
        torch.from_numpy((mask_padded > 0).astype(np.float32))
        .unsqueeze(0).unsqueeze(0).to(device)
    )

    lama_start = time.time()
    logger.info(f"[{request_id}] Inference started | device={device} | padded_size={rgb_padded.shape[:2]}")

    with torch.no_grad():
        batch = {'image': img_tensor, 'mask': mask_tensor}
        batch = MODEL(batch)

    duration = time.time() - lama_start
    logger.info(f"[{request_id}] Inference complete | duration={duration:.3f}s")

    # Result: [1, 3, H', W'] → [H', W', 3]
    result_padded = batch['inpainted'][0].permute(1, 2, 0).detach().cpu().numpy()

    # Explicit crop-back to original size (not delegated to the library).
    result = result_padded[:orig_h, :orig_w, :]

    if result.shape[:2] != (orig_h, orig_w):
        raise ProcessingError(
            'unexpected_output_size',
            f'Crop-back failed: expected {orig_h}×{orig_w}, got {result.shape[:2]}.'
        )

    return result  # float32 [H, W, 3] in [0, 1]


def composite_rgba(
    pil_image: Image.Image,
    lama_rgb: np.ndarray,
    mask_arr: np.ndarray,
) -> np.ndarray:
    """
    Compose the final RGBA result:
      mask == 255  →  RGB from LaMa inference
      mask == 0    →  RGB from original image (unchanged)
      alpha        →  always from original image (all pixels)

    This ensures that pixels outside the selection are bit-for-bit identical
    to the input, preventing accumulated rounding error across repeated edits.

    Returns:
        uint8 ndarray [H, W, 4]
    """
    orig_rgba  = np.array(pil_image, dtype=np.uint8)         # [H, W, 4]
    orig_rgb   = orig_rgba[:, :, :3]                          # [H, W, 3]
    orig_alpha = orig_rgba[:, :, 3:4]                         # [H, W, 1]

    lama_rgb_u8 = np.clip(lama_rgb * 255, 0, 255).astype(np.uint8)  # [H, W, 3]

    replace     = (mask_arr[:, :, np.newaxis] == 255)         # [H, W, 1] bool
    result_rgb  = np.where(replace, lama_rgb_u8, orig_rgb)    # [H, W, 3]

    return np.concatenate([result_rgb, orig_alpha], axis=2)   # [H, W, 4]

# ============================================================
# Routes
# ============================================================

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/output/<filename>')
def serve_output(filename):
    """Serve files from the output directory. GUI / manual verification use only."""
    return send_from_directory(app.config['OUTPUT_FOLDER'], filename)


@app.route('/status', methods=['GET'])
def get_status():
    """Return current server state. Used by the GUI to initialize controls."""
    return jsonify({
        'device':         DEVICE,
        'cuda_available': CUDA_AVAILABLE,
        'model_loaded':   MODEL is not None,
        'crop_mode':      CROP_MODE,
        'crop_margin':    CROP_MARGIN,
        'lan_access':     ALLOW_LAN_ACCESS,
    })


@app.route('/set_mode', methods=['POST'])
def set_mode():
    """
    Switch inference device between 'cpu' and 'cuda'.

    Waits for any running inference job to finish before switching
    (using _PROCESS_LOCK with a timeout). Returns 409 if a job does
    not finish within the timeout window.
    """
    global DEVICE, CROP_MODE

    data = request.get_json(silent=True) or {}
    new_device = str(data.get('device', '')).lower()

    if new_device not in ('cpu', 'cuda'):
        return jsonify({
            'error': 'invalid_device',
            'message': 'device must be "cpu" or "cuda".'
        }), 400

    if new_device == 'cuda' and not CUDA_AVAILABLE:
        return jsonify({
            'error': 'cuda_unavailable',
            'message': 'CUDA is not available on this machine.'
        }), 400

    if new_device == DEVICE:
        label = 'GPU' if DEVICE == 'cuda' else 'CPU'
        return jsonify({'device': DEVICE, 'message': f'Already in {label} mode.'})

    logger.info(f"Mode switch requested: {DEVICE} -> {new_device}")

    # Wait up to 30 s for any running inference job to complete before switching.
    # If inference is still running after the timeout, reject the request rather
    # than forcing an unsafe mid-inference device change.
    acquired = _PROCESS_LOCK.acquire(blocking=True, timeout=30)
    if not acquired:
        return jsonify({
            'error': 'busy',
            'message': 'A job is still running. Please wait for it to finish and try again.'
        }), 409

    try:
        if MODEL is not None:
            logger.info(f"Moving model to {new_device}...")
            MODEL.to(new_device)
            if new_device == 'cpu' and CUDA_AVAILABLE:
                torch.cuda.empty_cache()
                logger.info("CUDA cache cleared.")
        DEVICE = new_device

        # When switching to CPU, automatically enable crop mode to reduce
        # inference time. Switching back to GPU leaves crop mode as-is.
        if new_device == 'cpu':
            CROP_MODE = True
            logger.info("Crop mode auto-enabled for CPU inference.")

        label = 'GPU' if DEVICE == 'cuda' else 'CPU'
        logger.info(f"Mode switched to {new_device}")
        return jsonify({
            'device':    DEVICE,
            'crop_mode': CROP_MODE,
            'message':   f'Switched to {label} mode.',
        })
    except Exception as e:
        logger.exception(f"Failed to switch device to {new_device}: {e}")
        return jsonify({
            'error': 'internal_error',
            'message': f'Failed to switch to {new_device} mode. See server log.'
        }), 500
    finally:
        _PROCESS_LOCK.release()


@app.route('/set_lan_access', methods=['POST'])
def set_lan_access():
    """
    Toggle LAN access. When enabled, requests from any IP are allowed.
    When disabled, only localhost (127.0.0.1 / ::1) is permitted.

    Body (JSON):
        enabled (bool) — whether to allow LAN access
    """
    global ALLOW_LAN_ACCESS

    data = request.get_json(silent=True) or {}
    if 'enabled' not in data:
        return jsonify({
            'error': 'missing_fields',
            'message': '"enabled" field required.'
        }), 400

    ALLOW_LAN_ACCESS = bool(data['enabled'])
    logger.info(f"LAN access {'enabled' if ALLOW_LAN_ACCESS else 'disabled'}")
    return jsonify({'lan_access': ALLOW_LAN_ACCESS})


@app.route('/set_crop', methods=['POST'])
def set_crop():
    """
    Update crop mode settings.

    Body (JSON):
        enabled (bool)  — whether crop mode is active
        margin  (int)   — margin pixels around the mask bbox (0–500)
    """
    global CROP_MODE, CROP_MARGIN

    data = request.get_json(silent=True) or {}

    if 'enabled' not in data and 'margin' not in data:
        return jsonify({
            'error': 'missing_fields',
            'message': '"enabled" and/or "margin" field required.'
        }), 400

    if 'enabled' in data:
        CROP_MODE = bool(data['enabled'])

    if 'margin' in data:
        try:
            margin = int(data['margin'])
        except (TypeError, ValueError):
            return jsonify({
                'error': 'invalid_margin',
                'message': '"margin" must be an integer.'
            }), 400
        if not (0 <= margin <= 500):
            return jsonify({
                'error': 'invalid_margin',
                'message': '"margin" must be between 0 and 500.'
            }), 400
        CROP_MARGIN = margin

    logger.info(f"Crop settings updated | crop_mode={CROP_MODE} crop_margin={CROP_MARGIN}")
    return jsonify({
        'crop_mode':   CROP_MODE,
        'crop_margin': CROP_MARGIN,
    })


@app.route('/process', methods=['POST'])
def process_images():
    request_id = uuid.uuid4().hex[:8]
    start_time = time.time()

    logger.info(
        f"[{request_id}] Request received | "
        f"client={request.remote_addr} | "
        f"time={time.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    # --- Guard: reject immediately if another job or a mode switch is running ---
    if not _PROCESS_LOCK.acquire(blocking=False):
        logger.warning(f"[{request_id}] Rejected: busy")
        return jsonify({
            'error': 'busy',
            'message': 'Another inpainting job is already running.'
        }), 409

    try:
        # --- Input presence check ---
        if 'image' not in request.files or 'mask' not in request.files:
            logger.warning(f"[{request_id}] missing_files")
            return jsonify({
                'error': 'missing_files',
                'message': 'Both "image" and "mask" fields are required.'
            }), 400

        image_file = request.files['image']
        mask_file  = request.files['mask']

        # Log file sizes before the stream is consumed by PIL
        try:
            image_file.stream.seek(0, 2)
            image_bytes = image_file.stream.tell()
            image_file.stream.seek(0)
            mask_file.stream.seek(0, 2)
            mask_bytes = mask_file.stream.tell()
            mask_file.stream.seek(0)
            logger.info(
                f"[{request_id}] Files | "
                f"image={image_file.filename} ({image_bytes} bytes) | "
                f"mask={mask_file.filename} ({mask_bytes} bytes)"
            )
        except Exception:
            logger.info(
                f"[{request_id}] Files | "
                f"image={image_file.filename} | mask={mask_file.filename}"
            )

        # --- Validation ---
        try:
            pil_image, mask_arr = validate_inputs(image_file, mask_file)
        except ProcessingError as e:
            logger.warning(f"[{request_id}] Validation error: {e.code} | {e.message}")
            return jsonify({'error': e.code, 'message': e.message}), 400

        orig_w, orig_h = pil_image.size
        logger.info(f"[{request_id}] Validated | size={orig_w}x{orig_h}")

        # --- Prepare float RGB for LaMa ---
        rgba_arr  = np.array(pil_image, dtype=np.uint8)
        rgb_float = rgba_arr[:, :, :3].astype(np.float32) / 255.0  # [H, W, 3] in [0, 1]

        # --- Crop mode: limit inference to the mask bounding box ---
        crop_coords = None
        if CROP_MODE:
            bbox = get_mask_bbox(mask_arr)
            if bbox is None:
                logger.info(f"[{request_id}] Mask is empty — returning original image unchanged.")
                buf = io.BytesIO()
                pil_image.save(buf, format='PNG')
                buf.seek(0)
                return Response(buf.read(), mimetype='image/png')
            crop_coords = expand_crop_box(bbox, CROP_MARGIN, orig_w, orig_h)
            l, t, r, b = crop_coords
            logger.info(
                f"[{request_id}] Crop | bbox={bbox} margin={CROP_MARGIN}px "
                f"→ ({l},{t},{r},{b}) size={(r-l)}x{(b-t)}px"
            )
            rgb_for_lama  = rgb_float[t:b, l:r]
            mask_for_lama = mask_arr[t:b, l:r]
        else:
            rgb_for_lama  = rgb_float
            mask_for_lama = mask_arr

        # --- LaMa inference ---
        logger.info(f"[{request_id}] Inference started at {time.strftime('%Y-%m-%d %H:%M:%S')}")
        try:
            lama_rgb = run_lama_inference(rgb_for_lama, mask_for_lama, request_id)
        except ProcessingError as e:
            logger.error(f"[{request_id}] {e.code}: {e.message}")
            return jsonify({'error': e.code, 'message': e.message}), 500
        except Exception as e:
            logger.exception(f"[{request_id}] inference_failed: {e}")
            return jsonify({
                'error': 'inference_failed',
                'message': 'LaMa inference failed. See server log for details.'
            }), 500

        # --- Crop paste-back: reconstruct full-canvas lama_rgb before compositing ---
        if crop_coords is not None:
            l, t, r, b = crop_coords
            lama_rgb_full = rgb_float.copy()
            lama_rgb_full[t:b, l:r] = lama_rgb
            lama_rgb = lama_rgb_full

        # --- Compositing ---
        result_rgba = composite_rgba(pil_image, lama_rgb, mask_arr)

        # --- Final size guard ---
        if result_rgba.shape[:2] != (orig_h, orig_w):
            logger.error(
                f"[{request_id}] unexpected_output_size: "
                f"got {result_rgba.shape[:2]}, expected ({orig_h}, {orig_w})"
            )
            return jsonify({
                'error': 'unexpected_output_size',
                'message': 'Output size does not match input image size.'
            }), 500

        # --- Encode as PNG in memory ---
        result_pil = Image.fromarray(result_rgba, 'RGBA')
        buf = io.BytesIO()
        result_pil.save(buf, format='PNG')
        buf.seek(0)

        # --- Save latest result for GUI reference (non-fatal if it fails) ---
        try:
            latest_path = os.path.join(app.config['OUTPUT_FOLDER'], 'latest.png')
            result_pil.save(latest_path)
            logger.info(f"[{request_id}] Latest result saved: {latest_path}")
        except Exception as e:
            logger.warning(f"[{request_id}] Could not save latest.png (non-fatal): {e}")

        total_time = time.time() - start_time
        logger.info(f"[{request_id}] Complete | total={total_time:.3f}s")

        # Return the PNG directly in the response body.
        # Clients check Content-Type: image/png to distinguish success from error JSON.
        return Response(buf.read(), mimetype='image/png')

    finally:
        # Always release the lock, even if an unhandled exception escapes the try block.
        _PROCESS_LOCK.release()

# ============================================================
# Startup: log environment info and load model
# ============================================================

# load_model() is called here (outside __main__) so the model is loaded
# regardless of whether the app is started via direct execution or a WSGI server.
logger.info("=== SimpleLaMaEraser startup ===")
logger.info(f"  Start time   : {time.strftime('%Y-%m-%d %H:%M:%S')}")
logger.info(f"  Python       : {sys.version}")
logger.info(f"  torch        : {torch.__version__}")
logger.info(f"  torchvision  : {torchvision.__version__}")
if CUDA_AVAILABLE:
    logger.info(f"  CUDA version : {torch.version.cuda}")
    logger.info(f"  GPU          : {torch.cuda.get_device_name(0)}")
else:
    logger.info(f"  CUDA         : not available")
logger.info(f"  Device       : {DEVICE}")
logger.info(f"  Model path   : {MODEL_PATH}")
logger.info(f"  Max upload   : {MAX_UPLOAD_MB}MB")
logger.info(f"  LAN access   : {'enabled' if ALLOW_LAN_ACCESS else 'disabled (localhost only)'}")
load_model()

if __name__ == '__main__':
    HOST = '0.0.0.0'  # 家庭内LAN利用を想定。実アクセス制御は enforce_access_control() が担う。
    PORT = 7859
    logger.info(f"  Listening on : {HOST}:{PORT}")
    # debug=False: prevents the Werkzeug reloader from spawning a child process,
    # which would trigger a duplicate (and slow) model load.
    app.run(host=HOST, port=PORT, debug=False)
