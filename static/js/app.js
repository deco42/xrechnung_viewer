const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const status = document.getElementById('status');
const preview = document.getElementById('preview');
const loading = document.getElementById('loading');
const openNewTabBtn = document.getElementById('openNewTab');
const savePdfBtn = document.getElementById('savePdf');
const printPdfBtn = document.getElementById('printPdf');
const languageSelect = document.getElementById('language');

let currentFile = null;
let currentHtml = null;

['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, preventDefaults, false);
    document.body.addEventListener(eventName, preventDefaults, false);
});

function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
}

['dragenter', 'dragover'].forEach(eventName => {
    dropZone.addEventListener(eventName, () => {
        dropZone.classList.add('dragover');
    }, false);
});

['dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, () => {
        dropZone.classList.remove('dragover');
    }, false);
});

dropZone.addEventListener('drop', (e) => {
    const files = e.dataTransfer.files;
    if (files.length > 0) {
        handleFile(files[0]);
    }
});

fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
        handleFile(e.target.files[0]);
    }
});

languageSelect.addEventListener('change', () => {
    if (currentFile) {
        handleFile(currentFile);
    }
});

openNewTabBtn.addEventListener('click', () => {
    if (currentHtml) {
        const blob = new Blob([currentHtml], { type: 'text/html' });
        const url = URL.createObjectURL(blob);
        window.open(url, '_blank');
    }
});

printPdfBtn.addEventListener('click', async () => {
    if (!currentFile) {
        showStatus('error', 'Bitte zuerst eine Datei laden');
        return;
    }

    setLoading(true);
    printPdfBtn.disabled = true;

    try {
        const formData = new FormData();
        formData.append('file', currentFile);
        formData.append('lang', languageSelect.value);

        const response = await fetch('/export-pdf', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'PDF generation failed');
        }

        const blob = await response.blob();
        const url = URL.createObjectURL(blob);

        const printWindow = window.open(url, '_blank');
        if (printWindow) {
            printWindow.onload = () => {
                printWindow.print();
            };
        }
    } catch (error) {
        showStatus('error', 'PDF Error: ' + error.message);
    } finally {
        setLoading(false);
        printPdfBtn.disabled = false;
    }
});

savePdfBtn.addEventListener('click', async () => {
    if (!currentFile) return;

    setLoading(true);
    savePdfBtn.disabled = true;

    try {
        const formData = new FormData();
        formData.append('file', currentFile);
        formData.append('lang', languageSelect.value);

        const response = await fetch('/export-pdf', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'PDF generation failed');
        }

        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = currentFile ? currentFile.name.replace('.xml', '.pdf') : 'xrechnung.pdf';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        showStatus('success', 'PDF downloaded');
    } catch (error) {
        showStatus('error', 'PDF Error: ' + error.message);
    } finally {
        setLoading(false);
        savePdfBtn.disabled = false;
    }
});

async function handleFile(file) {
    if (!file.name.toLowerCase().endsWith('.xml')) {
        showStatus('error', 'Bitte eine XML-Datei auswählen');
        return;
    }

    currentFile = file;
    setLoading(true);
    dropZone.classList.remove('success', 'error');
    openNewTabBtn.disabled = true;
    savePdfBtn.disabled = true;
    printPdfBtn.disabled = true;

    const formData = new FormData();
    formData.append('file', file);
    formData.append('lang', languageSelect.value);

    try {
        const response = await fetch('/transform', {
            method: 'POST',
            body: formData
        });

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.error || 'Transformation failed');
        }

        currentHtml = result.html;

        preview.srcdoc = currentHtml;
        preview.classList.add('show');

        dropZone.classList.add('success');
        showStatus('success', `Erfolgreich geladen: <span class="filename">${file.name}</span>`);

        openNewTabBtn.disabled = false;
        savePdfBtn.disabled = !window.HAS_FOP;
        printPdfBtn.disabled = !window.HAS_FOP;

    } catch (error) {
        dropZone.classList.add('error');
        showStatus('error', 'Error: ' + error.message);
        preview.classList.remove('show');
    } finally {
        setLoading(false);
    }
}

function showStatus(type, message) {
    status.className = 'status show ' + type;
    status.innerHTML = message;
}

function setLoading(show) {
    loading.classList.toggle('show', show);
}
