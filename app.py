import os
import sys
import tempfile
import threading
import time
import uuid
import torch
import torchvision
from flask import Flask, request, jsonify, render_template, send_from_directory
from werkzeug.utils import secure_filename
import logging
import cv2
import numpy as np
from omegaconf import OmegaConf
from saicinpainting.training.trainers import load_checkpoint
from saicinpainting.evaluation.utils import move_to_device
from saicinpainting.training.data.datasets import make_default_val_dataset
from torch.utils.data._utils.collate import default_collate

# ---- Upload size limit ----
MAX_UPLOAD_MB = 64

# ---- Logging ----
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---- Base directory (directory containing this script) ----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---- Set environment variables once at startup, not per-request ----
os.environ['TORCH_HOME'] = BASE_DIR
os.environ['PYTHONPATH'] = BASE_DIR

# ---- CUDA check: fail fast if GPU is unavailable ----
if not torch.cuda.is_available():
    logger.error(
        f"CUDA is not available. "
        f"PyTorch version: {torch.__version__}, "
        f"CUDA available: {torch.cuda.is_available()}"
    )
    sys.exit(1)
DEVICE = 'cuda'

# ---- Model globals ----
MODEL_PATH = os.path.join(BASE_DIR, 'big-lama')
MODEL = None
_MODEL_LOAD_LOCK = threading.Lock()  # prevents concurrent model loads


def load_model():
    """Load the LaMa model into VRAM. Idempotent: safe to call multiple times."""
    global MODEL
    with _MODEL_LOAD_LOCK:
        if MODEL is not None:
            return
        logger.info(f"Model load started | path={MODEL_PATH}")
        config_path = os.path.join(MODEL_PATH, 'config.yaml')
        checkpoint_path = os.path.join(MODEL_PATH, 'models', 'best.ckpt')
        import yaml
        with open(config_path, 'r') as f:
            train_config = OmegaConf.create(yaml.safe_load(f))
        train_config.training_model.predict_only = True
        train_config.visualizer.kind = 'noop'
        MODEL = load_checkpoint(train_config, checkpoint_path, strict=False, map_location='cpu')
        MODEL.freeze()
        MODEL.to(DEVICE)
        logger.info("Model load complete | resident in VRAM (predict-only mode)")
        logger.info(f"ResNetPL in model: {'loss_resnet_pl' in dir(MODEL)}")


# ---- Flask app ----
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'output'
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_MB * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

# ---- Concurrent request guard ----
# This tool processes one image at a time. Concurrent /process calls would:
#   - spike GPU memory usage
#   - risk result file collisions
#   - confuse the calling paint tool about which result belongs to which request
_PROCESS_LOCK = threading.Lock()


# ---- Error handlers ----
@app.errorhandler(413)
def request_entity_too_large(e):
    return jsonify({
        'error': 'payload_too_large',
        'message': f'Upload size exceeds the {MAX_UPLOAD_MB}MB limit.'
    }), 413


# ---- Routes ----
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/output/<filename>')
def output_file(filename):
    return send_from_directory(app.config['OUTPUT_FOLDER'], filename)


@app.route('/process', methods=['POST'])
def process_images():
    request_id = uuid.uuid4().hex[:8]
    start_time = time.time()
    client_ip = request.remote_addr

    logger.info(
        f"[{request_id}] Request received | "
        f"client={client_ip} | "
        f"time={time.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    # ---- Reject if another request is already being processed ----
    if not _PROCESS_LOCK.acquire(blocking=False):
        logger.warning(f"[{request_id}] Rejected: busy (another request is in progress)")
        return jsonify({
            'error': 'busy',
            'message': 'Another inpainting request is already running.'
        }), 409

    try:
        # ---- Input validation ----
        if 'image' not in request.files or 'mask' not in request.files:
            logger.warning(f"[{request_id}] Rejected: missing_files")
            return jsonify({
                'error': 'missing_files',
                'message': 'Both image and mask files are required.'
            }), 400

        image_file = request.files['image']
        mask_file = request.files['mask']

        if image_file.filename == '' or mask_file.filename == '':
            logger.warning(f"[{request_id}] Rejected: empty filename")
            return jsonify({
                'error': 'missing_files',
                'message': 'No file was selected.'
            }), 400

        if not image_file.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff')):
            logger.warning(f"[{request_id}] Rejected: invalid_image | filename={image_file.filename}")
            return jsonify({
                'error': 'invalid_image',
                'message': 'Image file must be a valid image format.'
            }), 400

        if not mask_file.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff')):
            logger.warning(f"[{request_id}] Rejected: invalid_mask | filename={mask_file.filename}")
            return jsonify({
                'error': 'invalid_mask',
                'message': 'Mask file must be a valid image format.'
            }), 400

        # ---- Process in a temp directory ----
        with tempfile.TemporaryDirectory() as temp_dir:
            logger.info(f"[{request_id}] Temp dir created: {temp_dir}")

            image_filename = secure_filename(image_file.filename)
            mask_filename = secure_filename(mask_file.filename)

            base_image_name = os.path.splitext(image_filename)[0]
            image_save_filename = f"{base_image_name}.png"
            mask_save_filename = f"{base_image_name}_mask.png"
            image_path = os.path.join(temp_dir, image_save_filename)
            mask_path = os.path.join(temp_dir, mask_save_filename)

            image_file.save(image_path)
            mask_file.save(mask_path)

            image_size = os.path.getsize(image_path)
            mask_size = os.path.getsize(mask_path)
            logger.info(
                f"[{request_id}] Input saved | "
                f"image={image_filename} ({image_size} bytes) | "
                f"mask={mask_filename} ({mask_size} bytes)"
            )

            output_dir = app.config['OUTPUT_FOLDER']
            result_filename = f"{base_image_name}_result.png"
            result_path = os.path.join(output_dir, result_filename)

            try:
                dataset_config = {
                    'kind': 'default',
                    'img_suffix': '.png',
                    'pad_out_to_modulo': 8
                }
                dataset = make_default_val_dataset(temp_dir, **dataset_config)

                lama_start = time.time()
                logger.info(f"[{request_id}] Inference started at {time.strftime('%Y-%m-%d %H:%M:%S')}")

                with torch.no_grad():
                    batch = default_collate([dataset[0]])
                    batch = move_to_device(batch, DEVICE)
                    batch['mask'] = (batch['mask'] > 0) * 1
                    batch = MODEL(batch)
                    cur_res = batch['inpainted'][0].permute(1, 2, 0).detach().cpu().numpy()

                    cur_res = np.clip(cur_res * 255, 0, 255).astype('uint8')
                    cur_res = cv2.cvtColor(cur_res, cv2.COLOR_RGB2BGR)
                    cv2.imwrite(result_path, cur_res)

                lama_end = time.time()
                inference_time = lama_end - lama_start
                logger.info(
                    f"[{request_id}] Inference complete | "
                    f"duration={inference_time:.3f}s | "
                    f"output={result_path}"
                )

                if not os.path.exists(result_path):
                    logger.error(f"[{request_id}] Result file missing after inference: {result_path}")
                    return jsonify({
                        'error': 'processing_failed',
                        'message': 'Result file was not generated.'
                    }), 500

                total_time = time.time() - start_time
                logger.info(f"[{request_id}] Request complete | total={total_time:.3f}s")

                return jsonify({
                    'success': True,
                    'result_url': f'/output/{result_filename}'
                })

            except Exception as e:
                logger.exception(
                    f"[{request_id}] processing_failed during inference: {e}"
                )
                return jsonify({
                    'error': 'processing_failed',
                    'message': 'Inpainting failed. See server log for details.'
                }), 500

    finally:
        # Always release the lock, even if an exception propagated
        _PROCESS_LOCK.release()


# ---- Load model at module initialization ----
# Called here (outside __main__) so the model is loaded regardless of whether
# the app is started via direct execution or a WSGI server (e.g. gunicorn).
# Startup fails immediately and loudly if the model files are missing.
logger.info("=== SimpleLaMaEraser startup ===")
logger.info(f"  Start time   : {time.strftime('%Y-%m-%d %H:%M:%S')}")
logger.info(f"  Python       : {sys.version}")
logger.info(f"  torch        : {torch.__version__}")
logger.info(f"  torchvision  : {torchvision.__version__}")
logger.info(f"  CUDA version : {torch.version.cuda}")
logger.info(f"  GPU          : {torch.cuda.get_device_name(0)}")
logger.info(f"  Model path   : {MODEL_PATH}")
logger.info(f"  Max upload   : {MAX_UPLOAD_MB}MB")
load_model()

if __name__ == '__main__':
    # host='0.0.0.0': accepts connections from the local machine and home LAN.
    # Not intended for internet-facing deployment.
    HOST = '0.0.0.0'
    PORT = 7859
    logger.info(f"  Listening on : {HOST}:{PORT}")
    # debug=False: prevents the Werkzeug reloader from spawning a second process,
    # which would trigger a second (unnecessary and slow) model load.
    app.run(host=HOST, port=PORT, debug=False)
