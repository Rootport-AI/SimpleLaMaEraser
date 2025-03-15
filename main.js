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

    // File storage
    let imageFile = null;
    let maskFile = null;

    // Check if both files are selected to enable run button
    function updateRunButtonState() {
        runBtn.disabled = !(imageFile && maskFile);
    }

    // Handle file upload for images
    function handleImageUpload(file, previewElement, isImage = true) {
        if (!file) return;
        
        // Validate file is an image
        if (!file.type.match('image.*')) {
            alert('Please select an image file.');
            return;
        }
        
        // Validate mask is PNG if applicable
        if (!isImage && !file.type.match('image.*')) {
            alert('Mask must be an image file.');
            return;
        }
        
        // Create preview
        const reader = new FileReader();
        reader.onload = function(e) {
            previewElement.src = e.target.result;
            previewElement.style.display = 'block';
            
            // Hide drop message in the drop area
            previewElement.parentElement.parentElement.querySelector('.drop-message').style.display = 'none';
        };
        reader.readAsDataURL(file);
        
        // Store file reference
        if (isImage) {
            imageFile = file;
        } else {
            maskFile = file;
        }
        
        updateRunButtonState();
    }

    // Setup drag and drop for image
    function setupDragAndDrop(dropArea, fileInput, previewElement, isImage = true) {
        // Prevent default drag behaviors
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            dropArea.addEventListener(eventName, preventDefaults, false);
        });
        
        // Highlight drop area when dragging over it
        ['dragenter', 'dragover'].forEach(eventName => {
            dropArea.addEventListener(eventName, highlight, false);
        });
        
        ['dragleave', 'drop'].forEach(eventName => {
            dropArea.addEventListener(eventName, unhighlight, false);
        });
        
        // Handle dropped files
        dropArea.addEventListener('drop', function(e) {
            const file = e.dataTransfer.files[0];
            handleImageUpload(file, previewElement, isImage);
        }, false);
        
        // Open file dialog when clicked
        dropArea.addEventListener('click', function() {
            fileInput.click();
        });
        
        // Handle file selection via input
        fileInput.addEventListener('change', function() {
            const file = this.files[0];
            handleImageUpload(file, previewElement, isImage);
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

    // Set up browse buttons
    imageBrowseBtn.addEventListener('click', function() {
        imageUpload.click();
    });

    maskBrowseBtn.addEventListener('click', function() {
        maskUpload.click();
    });

    // Handle Run button click
    runBtn.addEventListener('click', function() {
        if (!imageFile || !maskFile) {
            alert('Please select both an image and a mask file.');
            return;
        }
        
        // Show loading indicator
        loadingIndicator.style.display = 'flex';
        resultImage.style.display = 'none';
        downloadContainer.style.display = 'none';
        
        // Create form data
        const formData = new FormData();
        formData.append('image', imageFile);
        formData.append('mask', maskFile);
        
        // Send to server
        fetch('/process', {
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            // Hide loading indicator
            loadingIndicator.style.display = 'none';
            
            if (data.error) {
                alert('Error: ' + data.error);
                return;
            }
            
            // Show result
            resultImage.src = data.result_url + '?t=' + new Date().getTime(); // Add timestamp to prevent caching
            resultImage.style.display = 'block';
            
            // Setup download link
            downloadLink.href = data.result_url;
            downloadContainer.style.display = 'block';
        })
        .catch(error => {
            loadingIndicator.style.display = 'none';
            alert('Error: ' + error.message);
            console.error('Error:', error);
        });
    });

    // Initialize drag and drop
    setupDragAndDrop(imageDropArea, imageUpload, imagePreview, true);
    setupDragAndDrop(maskDropArea, maskUpload, maskPreview, false);
});