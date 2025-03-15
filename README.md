# SimpleLaMaEraser 非エンジニア向けスピードガイド
SimpleLaMaEraser は画像から不要なオブジェクトを簡単に削除できるAIツールです。修正したい画像と、そのマスク画像を用意して、ドラッグ＆ドロップするだけ！同梱の「TestImages」で試してみてくださいね！

# 動作検証環境
- **OS**: Windows 10/11 (64-bit)
- **GPU**: 
  - NVIDIA GeForce RTX 4070 Ti SUPER (Driver: 572.60, CUDA: 12.8)
  - NVIDIA GeForce RTX 3080 Laptop GPU (Driver: 572.16, CUDA: 12.8)

1. Visual Studio 2022をインストールする。<br>
「C++によるデスクトップ開発」を選択すること！<br>
https://visualstudio.microsoft.com/ja/downloads/ <br>
2GBほどのサイズがあります。コミュニティ版なら無料で利用できます。<br>

2. Python 3.10 をインストールする。<br>
https://www.python.org/downloads/ <br>
3.10は最新版ではないので注意<br>

3. git をインストールする。<br>
https://git-scm.com/ <br>

4. SimpleLaMaEraserのダウンロード方法（zipの場合）<br>
「SimpleLaMaEraser.zip」をダウンロード。<br>
https://github.com/Rootport-AI/SimpleLaMaEraser/releases/download/v1.0.0/SimpleLaMaEraser.zip <br>
好きなフォルダで解凍する。<br>

5. SimpleLaMaEraserのインストール方法<br>
「setup.bat」をダブルクリック。<br>
コマンドプロンプト（黒い画面）が開き、インストーラーが動き始めます。<br>
初回インストールには20分程度かかります。<br>
最終的に7GBほどのファイルがダウンロードされます。<br>
途中で止まっているように見えても閉じないで！インストールは終わっていません。<br>
最終的に以下のメッセージが表示されたら、インストール完了です。一旦、コマンドプロンプトを閉じてください。<br>
```
Setting PYTHONPATH for saicinpainting...
Setup completed successfully.
Application installed in: C:\好きなのフォルダ\appfiles
続行するには何かキーを押してください . . .
```

6. SimpleLaMaEraserの起動方法<br>
「run.bat」をダブルクリック。<br>
コマンドプロンプト（黒い画面）が開き、SimpleLaMaEraserが起動します。<br>
このコマンドプロンプトは閉じないでください！<br>
起動には数秒～十数秒がかかります。<br>
最終的に以下のメッセージが表示されたら起動完了です。<br>
```
INFO:__main__:Model loaded and resident in VRAM (predict-only mode)
INFO:__main__:ResNetPL in model: False
WARNING:werkzeug: * Debugger is active!
INFO:werkzeug: * Debugger PIN: 299-622-548
```

7. SimpleLaMaEraserの使い方<br>
ブラウザで http://localhost:7859 にアクセスしてください。<br>
SimpleLaMaEraserの操作画面が開きます。<br>

8. SimpleLaMaEraserの終了方法<br>
コマンドプロンプトを閉じれば、そのまま終了します。<br>

9. その他・ヒント<br>
setup.batを起動すると、\appfiles というフォルダが生成されます。<br>
このフォルダよりも上の階層にあるものは削除しても問題ありません。<br>
必要なファイルはすべて\appfiles 以下にコピーされているためです。<br>

（分かる人向け）
Visual Studio 2022を丸ごとインストールしなくても、Visual C++をインストールするだけで本来なら動くはずです。
https://learn.microsoft.com/ja-jp/cpp/windows/latest-supported-vc-redist?view=msvc-170
ところが現在のVC++には、SimpleLaMaEraserを動かすために必要な「libomp140.x86_64.dll」というコンポーネントが含まれていないようです。このコンポーネントを一番安全にインストールする方法として、ここではVisual Studioを丸ごとインストールする方法を紹介しました。

# SimpleLaMaEraser README

## Overview

SimpleLaMaEraser is a user-friendly tool for image inpainting, powered by the LaMa (Large Mask Inpainting) model from Rootport-AI. It allows you to easily remove unwanted objects from images using a simple web interface. Built with Flask and optimized for GPU acceleration, this tool is perfect for both casual users and enthusiasts who want quick, high-quality results.

- **Repository**: [GitHub](https://github.com/yourusername/SimpleLaMaEraser) (Replace `yourusername` with your GitHub username!)
- **Model**: Based on [Rootport-AI/lama](https://github.com/Rootport-AI/lama) with the `big-lama` pretrained model from Hugging Face.
- **License**: MIT License (or adjust based on your preference).

## Features

- **Simple Web Interface**: Upload an image, draw a mask, and let the AI erase the unwanted parts.
- **GPU Support**: Leverages NVIDIA GPUs with CUDA for fast processing.
- **Cross-Platform**: Works on Windows with minimal setup.
- **Pretrained Model**: Uses the `big-lama` model for high-quality inpainting out of the box.

## Verified Environments

- **OS**: Windows 10/11 (64-bit)
- **GPU**: 
  - NVIDIA GeForce RTX 4070 Ti SUPER (Driver: 572.60, CUDA: 12.8)
  - NVIDIA GeForce RTX 3080 Laptop GPU (Driver: 572.16, CUDA: 12.8)
- **Python**: 3.10
- **Dependencies**: As listed in `require.txt` with `pip 23.0.1`
- **Software**: Visual Studio 2022 Community (Desktop development with C++ workload)

## Prerequisites

To run SimpleLaMaEraser, you'll need the following installed on your Windows machine:

1. **Python 3.10**: Download from [python.org](https://www.python.org/downloads/release/python-31011/). Make sure to check "Add Python to PATH" during installation.
2. **Git**: Install from [git-scm.com](https://git-scm.com/download/win) to clone the repository.
3. **Visual Studio 2022 Community**: Required for GPU support dependencies (e.g., OpenMP). Download from [visualstudio.microsoft.com](https://visualstudio.microsoft.com/downloads/). During installation, select the "Desktop development with C++" workload.
4. **NVIDIA GPU with CUDA**: Ensure your GPU supports CUDA (check [NVIDIA's CUDA GPUs list](https://developer.nvidia.com/cuda-gpus)). Install the latest NVIDIA driver from [nvidia.com](https://www.nvidia.com/Download/index.aspx).

## Installation

Follow these steps to set up SimpleLaMaEraser:

1. **Clone the Repository**:
```
   git clone https://github.com/yourusername/SimpleLaMaEraser.git
   cd SimpleLaMaEraser

```

2. **Run the Setup Script**:
- Double-click `setup.bat` in the cloned folder.
- This script will:
  - Create a virtual environment.
  - Install dependencies (including PyTorch with CUDA 12.1 support).
  - Download the `big-lama` model from Hugging Face.
- Wait for the process to complete (it may take a few minutes depending on your internet speed).

3. **Verify Setup**:
- Once `setup.bat` finishes, you'll see "Setup completed successfully" in the command prompt.

## Usage

1. **Start the Tool**:
- Double-click `run.bat` in the `SimpleLaMaEraser` folder.
- The tool will launch a local web server.

2. **Access the Interface**:
- Open your browser and go to `http://localhost:7859`.
- Upload an image, draw a mask over the area you want to remove, and click "Process".

3. **View Results**:
- The processed image will appear in the browser. Download it if needed!

## Performance

- **Processing Time**: Depends on your GPU:
  - NVIDIA RTX 4070 Ti SUPER: ~0.6-1.0 seconds per image.
  - NVIDIA RTX 3080 Laptop GPU: ~1.4-1.6 seconds per image.
- **Requirements**: At least 16GB of GPU memory recommended for smooth operation.

## Troubleshooting

- **"Failed to install requirements"**:
  - Ensure Python 3.10 and Git are in your PATH (`python --version` and `git --version` to check).
  - Check your internet connection for downloading dependencies.
- **"CUDA not available"**:
  - Verify your NVIDIA driver is up-to-date and supports CUDA 12.1.
- **Slow performance**:
  - Confirm your GPU is detected (`nvidia-smi` in Command Prompt).
- **Still stuck?**:
  - Open an issue on [GitHub](https://github.com/yourusername/SimpleLaMaEraser/issues).

## Technical Details

- **Dependencies**: Listed in `require.txt`. Key packages include:
  - `torch==2.4.0+cu121`
  - `torchvision==0.19.0+cu121`
  - `pytorch-lightning>=1.7.1,<1.8.0` (requires `pip 23.0.1` for compatibility).
- **Setup Script**: `setup.bat` uses `pip 23.0.1` to avoid metadata issues with newer `pip` versions.
- **Model**: `big-lama` from [Hugging Face](https://huggingface.co/smartywu/big-lama).

## Contributing

Feel free to fork the repo and submit pull requests! Suggestions for improving the UI, performance, or compatibility are welcome.

## Acknowledgments

- Thanks to [Rootport-AI](https://github.com/Rootport-AI) for the GPU-enhanced LaMa fork.
- `big-lama` model by [smartywu](https://huggingface.co/smartywu).
- Built with love for non-engineers to enjoy AI magic!

## License

MIT License - feel free to use, modify, and distribute this tool as you like.

---
Happy inpainting with SimpleLaMaEraser!