const dropzone = document.getElementById('dropzone');
const fileNames = document.getElementById('fileNames');
const manualCityInput = document.getElementById('manualCityInput');
const uploadButton = document.getElementById('uploadButton');
let uploadedFiles = [];
let uploading = false;

function showManualCity(message) {
  alert(message);
  manualCityInput.style.display = 'block';
}

async function uploadFiles(location) {
  if (uploading) return;
  if (!uploadedFiles.length) {
    alert('Please drop at least one file first.');
    return;
  }
  const formData = new FormData();
  uploadedFiles.forEach((file) => formData.append('files[]', file));
  Object.entries(location).forEach(([name, value]) => formData.append(name, value));
  uploading = true;
  uploadButton.disabled = true;
  try {
    const response = await fetch('/upload', { method: 'POST', body: formData });
    const data = await response.json();
    if (data.manual_city_required) {
      showManualCity(data.message);
    } else if (!response.ok) {
      alert(data.message || 'Upload failed. Please try again.');
    } else {
      alert(data.message);
      uploadedFiles = [];
      fileNames.innerHTML = '';
      manualCityInput.style.display = 'none';
    }
  } catch (error) {
    alert('Error: ' + error.message);
  } finally {
    uploading = false;
    uploadButton.disabled = false;
  }
}

dropzone.addEventListener('dragover', (event) => event.preventDefault());
dropzone.addEventListener('drop', (event) => {
  event.preventDefault();
  if (uploading) {
    alert('Please wait for the current upload to finish.');
    return;
  }
  uploadedFiles = Array.from(event.dataTransfer.files);
  fileNames.innerHTML = '';
  uploadedFiles.forEach((file) => {
    const item = document.createElement('li');
    item.textContent = file.name;
    fileNames.appendChild(item);
  });
  manualCityInput.style.display = 'none';
  if (!uploadedFiles.length) return;
  if (!navigator.geolocation) {
    showManualCity('Geolocation is unavailable. Please enter a city name.');
    return;
  }
  navigator.geolocation.getCurrentPosition(
    (position) => uploadFiles({
      latitude: position.coords.latitude,
      longitude: position.coords.longitude,
    }),
    (error) => showManualCity('Geolocation error: ' + error.message),
    { timeout: 10000 },
  );
});

uploadButton.addEventListener('click', () => {
  const city = document.getElementById('manual_city').value.trim();
  if (!city) {
    alert('Please enter a city name.');
    return;
  }
  uploadFiles({ manual_city: city });
});
