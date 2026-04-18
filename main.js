// Apply dark mode class immediately (before DOMContentLoaded) to prevent FOUC.
// This is the runtime counterpart of the inline script in <head>.
(function() {
    if (localStorage.getItem('theme') !== 'light') {
        document.documentElement.classList.add('dark');
    }
})();

document.addEventListener('DOMContentLoaded', function() {
    // DOM elements
    const imageDropArea = document.getElementById('image-drop-area');
    const maskDropArea = document.getElementById('mask-drop-area');
    const imageUpload = document.getElementById('image-upload');
    const maskUpload = document.getElementById('mask-upload');
    const imagePreview = document.getElementById('image-preview');
    const maskPreview = document.getElementById('mask-preview');
    const imageBrowseBtn = document.getElementById('image-browse-btn');
    const maskBrowseBtn = document.getElementById('mask-browse-btn');
    const runBtn = document.getElementById('run-btn');
    const resultImage = document.getElementById('result-image');
    const loadingIndicator = document.getElementById('loading-indicator');
    const downloadContainer = document.getElementById('download-container');
    const downloadLink = document.getElementById('download-link');

    // Mode selector elements
    const modeGpu = document.getElementById('mode-gpu');
    const modeCpu = document.getElementById('mode-cpu');
    const modeStatus = document.getElementById('mode-status');

    // LAN access elements
    const lanEnabled = document.getElementById('lan-enabled');
    const lanStatus  = document.getElementById('lan-status');

    // Crop selector elements
    const cropEnabled     = document.getElementById('crop-enabled');
    const cropMargin      = document.getElementById('crop-margin');
    const cropMarginValue = document.getElementById('crop-margin-value');
    const marginControl   = document.getElementById('margin-control');
    const cropStatus      = document.getElementById('crop-status');

    // Theme toggle
    const themeToggle = document.getElementById('theme-toggle');

    // File storage
    let imageFile = null;
    let maskFile = null;

    // Track the current result Blob URL so it can be revoked when a new result arrives.
    let currentResultUrl = null;

    // Whether the GPU radio was ever enabled (used to restore it after a switch).
    let cudaAvailable = false;

    // ============================================================
    // Dark mode toggle
    // ============================================================

    themeToggle.addEventListener('click', function() {
        var isDark = document.documentElement.classList.toggle('dark');
        localStorage.setItem('theme', isDark ? 'dark' : 'light');
    });

    // ============================================================
    // Mode selector
    // ============================================================

    function setModeStatus(text, cls) {
        modeStatus.textContent = text;
        modeStatus.className = 'mode-status' + (cls ? ' ' + cls : '');
    }

    function setRadiosEnabled(enabled) {
        modeCpu.disabled = !enabled;
        // GPU is only re-enabled if CUDA is actually available
        modeGpu.disabled = !enabled || !cudaAvailable;
    }

    // Fetch server status on page load to initialize the radio buttons and crop controls.
    function fetchStatus() {
        fetch('/status')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                cudaAvailable = data.cuda_available;

                if (data.device === 'cuda') {
                    modeGpu.checked = true;
                } else {
                    modeCpu.checked = true;
                }

                if (!data.cuda_available) {
                    modeGpu.disabled = true;
                    modeGpu.parentElement.title = 'CUDAが利用できない環境です';
                }

                setModeStatus('');

                // Initialize LAN access checkbox from server state
                lanEnabled.checked = !!data.lan_access;

                // Initialize crop controls from server state
                cropEnabled.checked = !!data.crop_mode;
                cropMargin.value = data.crop_margin != null ? data.crop_margin : 128;
                cropMarginValue.textContent = cropMargin.value + 'px';
                updateMarginControlState();
            })
            .catch(function() {
                setModeStatus('サーバーに接続できません', 'error');
            });
    }

    // Called when a radio button is clicked.
    function handleModeChange(e) {
        var newDevice = e.target.value;

        // Disable both radios while the switch is in progress.
        setRadiosEnabled(false);
        setModeStatus('切り替え中...', 'switching');

        fetch('/set_mode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ device: newDevice })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) {
                // Revert the radio to the opposite selection on failure.
                if (newDevice === 'cuda') {
                    modeCpu.checked = true;
                } else {
                    modeGpu.checked = true;
                }
                setModeStatus(data.message || data.error, 'error');
            } else {
                setModeStatus(data.message || '', 'ok');
                setTimeout(function() { setModeStatus(''); }, 3000);

                // If the server auto-enabled crop mode (CPU switch), sync the checkbox.
                if (data.crop_mode != null) {
                    cropEnabled.checked = !!data.crop_mode;
                    updateMarginControlState();
                }
            }
        })
        .catch(function() {
            // Network error — revert radio and show error.
            if (newDevice === 'cuda') {
                modeCpu.checked = true;
            } else {
                modeGpu.checked = true;
            }
            setModeStatus('切り替えに失敗しました', 'error');
        })
        .finally(function() {
            setRadiosEnabled(true);
        });
    }

    modeGpu.addEventListener('change', handleModeChange);
    modeCpu.addEventListener('change', handleModeChange);

    // Initialize UI from server state.
    fetchStatus();

    // ============================================================
    // LAN access toggle
    // ============================================================

    function setLanStatus(text, cls) {
        lanStatus.textContent = text;
        lanStatus.className = 'mode-status' + (cls ? ' ' + cls : '');
    }

    lanEnabled.addEventListener('change', function() {
        setLanStatus('送信中...', 'switching');

        fetch('/set_lan_access', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: lanEnabled.checked })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) {
                lanEnabled.checked = !lanEnabled.checked;
                setLanStatus(data.message || data.error, 'error');
            } else {
                setLanStatus(lanEnabled.checked ? 'LANアクセス有効' : 'LANアクセス無効', 'ok');
                setTimeout(function() { setLanStatus(''); }, 3000);
            }
        })
        .catch(function() {
            lanEnabled.checked = !lanEnabled.checked;
            setLanStatus('設定の送信に失敗しました', 'error');
        });
    });

    // ============================================================
    // Crop selector
    // ============================================================

    function setCropStatus(text, cls) {
        cropStatus.textContent = text;
        cropStatus.className = 'mode-status' + (cls ? ' ' + cls : '');
    }

    function updateMarginControlState() {
        if (cropEnabled.checked) {
            marginControl.classList.remove('disabled');
            cropMargin.disabled = false;
        } else {
            marginControl.classList.add('disabled');
            cropMargin.disabled = true;
        }
    }

    function postCropSettings(enabled, margin) {
        return fetch('/set_crop', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: enabled, margin: margin })
        })
        .then(function(r) { return r.json(); });
    }

    cropEnabled.addEventListener('change', function() {
        updateMarginControlState();
        setCropStatus('送信中...', 'switching');

        postCropSettings(cropEnabled.checked, parseInt(cropMargin.value, 10))
            .then(function(data) {
                if (data.error) {
                    // Revert checkbox on failure
                    cropEnabled.checked = !cropEnabled.checked;
                    updateMarginControlState();
                    setCropStatus(data.message || data.error, 'error');
                } else {
                    setCropStatus(cropEnabled.checked ? 'Cropモード有効' : 'Cropモード無効', 'ok');
                    setTimeout(function() { setCropStatus(''); }, 3000);
                }
            })
            .catch(function() {
                cropEnabled.checked = !cropEnabled.checked;
                updateMarginControlState();
                setCropStatus('設定の送信に失敗しました', 'error');
            });
    });

    // Update displayed value while dragging (no server call yet)
    cropMargin.addEventListener('input', function() {
        cropMarginValue.textContent = cropMargin.value + 'px';
    });

    // Send to server when the user releases the slider
    cropMargin.addEventListener('change', function() {
        setCropStatus('送信中...', 'switching');
        postCropSettings(cropEnabled.checked, parseInt(cropMargin.value, 10))
            .then(function(data) {
                if (data.error) {
                    setCropStatus(data.message || data.error, 'error');
                } else {
                    setCropStatus('マージン更新済み', 'ok');
                    setTimeout(function() { setCropStatus(''); }, 3000);
                }
            })
            .catch(function() {
                setCropStatus('設定の送信に失敗しました', 'error');
            });
    });

    // ============================================================
    // File handling
    // ============================================================

    function updateRunButtonState() {
        runBtn.disabled = !(imageFile && maskFile);
    }

    function handleImageUpload(file, previewElement, isImage) {
        if (!file) return;

        if (!file.type.match('image.*')) {
            alert('Please select an image file.');
            return;
        }

        const reader = new FileReader();
        reader.onload = function(e) {
            previewElement.src = e.target.result;
            previewElement.style.display = 'block';
            previewElement.parentElement.parentElement.querySelector('.drop-message').style.display = 'none';
        };
        reader.readAsDataURL(file);

        if (isImage) {
            imageFile = file;
        } else {
            maskFile = file;
        }

        updateRunButtonState();
    }

    function setupDragAndDrop(dropArea, fileInput, previewElement, isImage) {
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(function(eventName) {
            dropArea.addEventListener(eventName, preventDefaults, false);
        });

        ['dragenter', 'dragover'].forEach(function(eventName) {
            dropArea.addEventListener(eventName, highlight, false);
        });

        ['dragleave', 'drop'].forEach(function(eventName) {
            dropArea.addEventListener(eventName, unhighlight, false);
        });

        dropArea.addEventListener('drop', function(e) {
            handleImageUpload(e.dataTransfer.files[0], previewElement, isImage);
        }, false);

        dropArea.addEventListener('click', function() {
            fileInput.click();
        });

        fileInput.addEventListener('change', function() {
            handleImageUpload(this.files[0], previewElement, isImage);
        });
    }

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    function highlight() {
        this.classList.add('drag-over');
    }

    function unhighlight() {
        this.classList.remove('drag-over');
    }

    imageBrowseBtn.addEventListener('click', function() { imageUpload.click(); });
    maskBrowseBtn.addEventListener('click',  function() { maskUpload.click();  });

    // ============================================================
    // Run button: send image + mask, receive PNG directly
    // ============================================================

    runBtn.addEventListener('click', function() {
        if (!imageFile || !maskFile) {
            alert('Please select both an image and a mask file.');
            return;
        }

        loadingIndicator.style.display = 'flex';
        resultImage.style.display = 'none';
        downloadContainer.style.display = 'none';

        const formData = new FormData();
        formData.append('image', imageFile);
        formData.append('mask', maskFile);

        fetch('/process', {
            method: 'POST',
            body: formData
        })
        .then(function(response) {
            const contentType = response.headers.get('content-type') || '';
            if (contentType.startsWith('image/png')) {
                // Success: server returned the result PNG directly
                return response.blob().then(function(blob) {
                    return { type: 'image', blob: blob };
                });
            }
            // Error or unexpected: parse as JSON
            return response.json().then(function(data) {
                return { type: 'json', ok: response.ok, data: data };
            });
        })
        .then(function(result) {
            loadingIndicator.style.display = 'none';

            if (result.type === 'image') {
                // Revoke the previous Blob URL to avoid memory leaks
                if (currentResultUrl) {
                    URL.revokeObjectURL(currentResultUrl);
                }
                currentResultUrl = URL.createObjectURL(result.blob);

                resultImage.src = currentResultUrl;
                resultImage.style.display = 'block';

                downloadLink.href = currentResultUrl;
                downloadLink.download = 'result.png';
                downloadContainer.style.display = 'block';
            } else {
                const msg = (result.data && (result.data.message || result.data.error)) || 'Unknown error';
                alert('Error: ' + msg);
            }
        })
        .catch(function(error) {
            loadingIndicator.style.display = 'none';
            alert('Error: ' + error.message);
            console.error('Error:', error);
        });
    });

    // ============================================================
    // Initialize drag and drop
    // ============================================================

    setupDragAndDrop(imageDropArea, imageUpload, imagePreview, true);
    setupDragAndDrop(maskDropArea,  maskUpload,  maskPreview,  false);
});
