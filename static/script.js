const video = document.getElementById("video");
const blinkStatus = document.getElementById("blinkStatus");

let blinkDetected = false;
let lastEyeOpen = true;
let cameraStream = null;

/* ===========================
   CAMERA ACCESS
=========================== */
navigator.mediaDevices.getUserMedia({ video: true })
.then(stream => {
    cameraStream = stream;
    video.srcObject = stream;
})
.catch(() => {
    alert("Camera access denied.");
});

/* ===========================
   MEDIAPIPE FACE MESH
=========================== */
const faceMesh = new FaceMesh({
    locateFile: (file) => {
        return `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/${file}`;
    }
});

faceMesh.setOptions({
    maxNumFaces: 1,
    refineLandmarks: true,
    minDetectionConfidence: 0.5,
    minTrackingConfidence: 0.5
});

faceMesh.onResults(results => {
    if (results.multiFaceLandmarks.length > 0) {

        const landmarks = results.multiFaceLandmarks[0];

        const leftEyeTop = landmarks[159];
        const leftEyeBottom = landmarks[145];

        const eyeDistance = Math.abs(leftEyeTop.y - leftEyeBottom.y);

        if (eyeDistance < 0.01 && lastEyeOpen) {
            blinkDetected = true;
            blinkStatus.innerText = "Blink detected ✅";
        }

        lastEyeOpen = eyeDistance > 0.01;
    }
});

const camera = new Camera(video, {
    onFrame: async () => {
        await faceMesh.send({ image: video });
    },
    width: 400,
    height: 300
});

camera.start();

/* ===========================
   UI HELPERS
=========================== */

function showSpinner(show) {
    const spinner = document.getElementById("spinner");
    if (spinner) spinner.style.display = show ? "block" : "none";
}

function showSuccess(message) {
    const box = document.getElementById("successBox");
    const error = document.getElementById("errorBox");

    if (box) {
        box.innerHTML = message;
        box.style.display = "block";
    }

    if (error) error.style.display = "none";
}

function showError(message) {
    const box = document.getElementById("errorBox");
    const success = document.getElementById("successBox");

    if (box) {
        box.innerHTML = message;
        box.style.display = "block";
    }

    if (success) success.style.display = "none";
}

function resetUI() {
    blinkDetected = false;
    blinkStatus.innerText = "Please blink to verify";
}

function freezeCamera() {
    if (cameraStream) {
        cameraStream.getTracks().forEach(track => track.stop());
    }
}

function playSuccessSound() {
    const audio = new Audio("https://actions.google.com/sounds/v1/cartoon/clang_and_wobble.ogg");
    audio.play();
}

/* ===========================
   IMAGE CAPTURE
=========================== */
function captureImage() {
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0);
    return canvas.toDataURL("image/jpeg");
}

/* ===========================
   ATTENDANCE
=========================== */
function captureAttendance() {

    if (!blinkDetected) {
        alert("Please blink to verify liveness.");
        return;
    }

    const btn = document.getElementById("attendanceBtn");
    if (btn) btn.disabled = true;

    showSpinner(true);

    fetch("/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image: captureImage() })
    })
    .then(res => res.json())
    .then(data => {

        showSpinner(false);
        if (btn) btn.disabled = false;

        if (data.status === "SUCCESS") {

            showSuccess(`
                ✅ Attendance Marked Successfully<br>
                <strong>${data.employee}</strong><br>
                Employee ID: ${data.emp_id}
            `);

            playSuccessSound();
            freezeCamera();

        } 
        else if (data.status === "ALREADY_MARKED") {

            showError(`
                ⚠ Your attendance for today is already marked.<br>
                <strong>${data.employee}</strong><br>
                Employee ID: ${data.emp_id}
            `);

        } 
        else {
            showError(data.status);
        }

        resetUI();

    })
    .catch(() => {
        showSpinner(false);
        if (btn) btn.disabled = false;
        showError("Something went wrong. Please try again.");
    });
}

/* ===========================
   REGISTRATION (ENTERPRISE)
=========================== */
function registerFace() {

    if (!blinkDetected) {
        alert("Please blink to verify liveness.");
        return;
    }

    const empId = document.getElementById("employee_id").value.trim();
    const workMode = document.getElementById("work_mode").value;

    if (!empId || !workMode) {
        showError("Emp_ID and Work Mode are required.");
        return;
    }

    const btn = document.querySelector(".btn");
    if (btn) btn.disabled = true;

    showSpinner(true);

    fetch("/register_face", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            image: captureImage(),
            employee_id: empId,
            work_mode: workMode
        })
    })
    .then(res => res.json())
    .then(data => {

        showSpinner(false);
        if (btn) btn.disabled = false;

        if (data.status === "REGISTERED") {

            showSuccess(`
                ✅ Registration Successful<br>
                Employee: <strong>${data.employee}</strong>
            `);

            playSuccessSound();
            freezeCamera();

        } 
        else if (data.status === "ALREADY_REGISTERED") {

            showError(`
                ⚠ Employee already registered:<br>
                <strong>${data.employee}</strong>
            `);

        } 
        else {
            showError(data.status);
        }

        resetUI();
    })
    .catch(() => {
        showSpinner(false);
        if (btn) btn.disabled = false;
        showError("Registration failed. Try again.");
    });
}