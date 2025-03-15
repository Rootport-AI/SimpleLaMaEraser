import os
import sys
import tempfile
import torch
import time
from flask import Flask, request, jsonify, render_template, send_from_directory
from werkzeug.utils import secure_filename
import logging
import shutil
import cv2
import numpy as np
from omegaconf import OmegaConf
from saicinpainting.training.trainers import load_checkpoint
from saicinpainting.evaluation.utils import move_to_device
from saicinpainting.training.data.datasets import make_default_val_dataset
from torch.utils.data._utils.collate import default_collate

# グローバルでモデルを保持
MODEL = None

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'output'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Ensure upload and output directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

# Get the directory of the current script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Check if CUDA is available
if not torch.cuda.is_available():
    logger.error(f"CUDA is not available. PyTorch version: {torch.__version__}, CUDA available: {torch.cuda.is_available()}")
    sys.exit(1)
DEVICE = 'cuda'
logger.info(f"Using device: {DEVICE}, CUDA version: {torch.version.cuda}, GPU: {torch.cuda.get_device_name(0)}")

# Define model path
MODEL_PATH = os.path.join(BASE_DIR, 'big-lama')

# モデルを事前ロードする関数（推論専用）
def load_model():
    global MODEL
    if MODEL is None:
        config_path = os.path.join(MODEL_PATH, 'config.yaml')
        checkpoint_path = os.path.join(MODEL_PATH, 'models', 'best.ckpt')
        with open(config_path, 'r') as f:
            import yaml
            train_config = OmegaConf.create(yaml.safe_load(f))
        train_config.training_model.predict_only = True
        train_config.visualizer.kind = 'noop'
        MODEL = load_checkpoint(train_config, checkpoint_path, strict=False, map_location='cpu')
        MODEL.freeze()
        MODEL.to(DEVICE)
        logger.info("Model loaded and resident in VRAM (predict-only mode)")
        logger.info(f"ResNetPL in model: {'loss_resnet_pl' in dir(MODEL)}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/output/<filename>')
def output_file(filename):
    return send_from_directory(app.config['OUTPUT_FOLDER'], filename)

@app.route('/process', methods=['POST'])
def process_images():
    start_time = time.time()
    app.logger.info(f"Process started at {start_time}")
    
    if 'image' not in request.files or 'mask' not in request.files:
        return jsonify({'error': 'Both image and mask files are required'}), 400
    
    image_file = request.files['image']
    mask_file = request.files['mask']
    
    if image_file.filename == '' or mask_file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if not image_file.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff')):
        return jsonify({'error': 'Image file must be a valid image format'}), 400

    if not mask_file.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff')):
        return jsonify({'error': 'Mask file must be an image'}), 400
    
    with tempfile.TemporaryDirectory() as temp_dir:
        image_filename = secure_filename(image_file.filename)
        mask_filename = secure_filename(mask_file.filename)
        
        base_image_name = os.path.splitext(image_filename)[0]
        mask_save_filename = f"{base_image_name}_mask.png"
        image_save_filename = f"{base_image_name}.png"
        image_path = os.path.join(temp_dir, image_save_filename)
        mask_path = os.path.join(temp_dir, mask_save_filename)

        image_file.save(image_path)
        mask_file.save(mask_path)
        
        logger.info(f"Saved image to {image_path}")
        logger.info(f"Saved mask to {mask_path}")
        
        output_dir = app.config['OUTPUT_FOLDER']
        result_filename = f"{base_image_name}_result.png"
        result_path = os.path.join(output_dir, result_filename)
        
        try:
            os.environ['TORCH_HOME'] = BASE_DIR
            os.environ['PYTHONPATH'] = BASE_DIR
            
            lama_start_time = time.time()
            
            # データセット設定
            dataset_config = {
                'kind': 'default',
                'img_suffix': '.png',
                'pad_out_to_modulo': 8
            }
            dataset = make_default_val_dataset(temp_dir, **dataset_config)
            
            # 推論
            with torch.no_grad():
                batch = default_collate([dataset[0]])  # 1枚だけ処理
                batch = move_to_device(batch, DEVICE)
                batch['mask'] = (batch['mask'] > 0) * 1
                batch = MODEL(batch)
                cur_res = batch['inpainted'][0].permute(1, 2, 0).detach().cpu().numpy()
                
                # 後処理
                cur_res = np.clip(cur_res * 255, 0, 255).astype('uint8')
                cur_res = cv2.cvtColor(cur_res, cv2.COLOR_RGB2BGR)
                cv2.imwrite(result_path, cur_res)
            
            lama_end_time = time.time()
            logger.info(f"LaMa processing took {lama_end_time - lama_start_time} seconds")
            
            if not os.path.exists(result_path):
                logger.error(f"Result file not found: {result_path}")
                return jsonify({'error': 'Result file not generated'}), 500
            
            total_end_time = time.time()
            logger.info(f"Total process took {total_end_time - start_time} seconds")
            
            return jsonify({
                'success': True,
                'result_url': f'/output/{result_filename}'
            })
            
        except Exception as e:
            logger.exception(f"Error during processing: {str(e)}")
            return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    load_model()
    app.run(host='0.0.0.0', port=7859, debug=True)