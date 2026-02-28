from flask import Flask, render_template, request, jsonify
import face_recognition
import numpy as np
import os
import json
from datetime import datetime
import base64
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ==============================
# APP CONFIG
# ==============================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

# Ensure folders exist
os.makedirs("encodings", exist_ok=True)

# ==============================
# LOAD REGISTERED EMPLOYEES
# ==============================
if os.path.exists("employees.json") and os.path.getsize("employees.json") > 0:
    with open("employees.json") as f:
        employees = json.load(f)
else:
    employees = {}

# ==============================
# LOAD FACE ENCODINGS
# ==============================
known_face_encodings = []
known_face_ids = []

def load_encodings():
    global known_face_encodings, known_face_ids
    known_face_encodings = []
    known_face_ids = []

    for emp_id in employees:
        encoding_path = f"encodings/{emp_id}.npy"
        if os.path.exists(encoding_path):
            encoding = np.load(encoding_path)
            known_face_encodings.append(encoding)
            known_face_ids.append(emp_id)

load_encodings()

# ==============================
# GOOGLE SHEETS SETUP (SECURE)
# ==============================
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

google_creds_json = os.environ.get("GOOGLE_CREDENTIALS")

if not google_creds_json:
    raise Exception("GOOGLE_CREDENTIALS environment variable not set.")

with open("credentials.json", "w") as f:
    f.write(google_creds_json)

creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)

spreadsheet = client.open("viTan HR System")
attendance_sheet = spreadsheet.worksheet("attendance_raw")
employees_master_sheet = spreadsheet.worksheet("Employees_Master")

# ==============================
# ROUTES
# ==============================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/register")
def register_page():
    return render_template("register.html")

# ==============================
# ENTERPRISE REGISTER FACE
# ==============================
@app.route("/register_face", methods=["POST"])
def register_face():

    try:
        data = request.json
        emp_id = data["employee_id"].strip()
        work_mode = data["work_mode"].strip()
        image_data = base64.b64decode(data["image"].split(",")[1])

        if not emp_id or not work_mode:
            return jsonify({"status": "Emp_ID and Work Mode required"})

        # Validate from Employees_Master
        master_records = employees_master_sheet.get_all_records()
        employee_record = None

        for record in master_records:
            if str(record["Emp_ID"]) == str(emp_id):
                employee_record = record
                break

        if not employee_record:
            return jsonify({"status": "Emp_ID not found in Employees_Master"})

        if employee_record["Status"].strip().lower() != "active":
            return jsonify({"status": "Employee is not Active"})

        if emp_id in employees:
            return jsonify({
                "status": "ALREADY_REGISTERED",
                "employee": employees[emp_id]["name"]
            })

        # Process face image
        with open("temp.jpg", "wb") as f:
            f.write(image_data)

        image = face_recognition.load_image_file("temp.jpg")
        encodings = face_recognition.face_encodings(image)

        os.remove("temp.jpg")

        if not encodings:
            return jsonify({"status": "No face detected"})

        encoding = encodings[0]
        np.save(f"encodings/{emp_id}.npy", encoding)

        employees[emp_id] = {
            "name": employee_record["Name"],
            "email": employee_record["Email"],
            "work_mode": work_mode
        }

        with open("employees.json", "w") as f:
            json.dump(employees, f, indent=4)

        load_encodings()

        return jsonify({
            "status": "REGISTERED",
            "employee": employee_record["Name"]
        })

    except Exception as e:
        return jsonify({"status": f"Registration error: {str(e)}"})


# ==============================
# VERIFY & MARK ATTENDANCE
# ==============================
@app.route("/verify", methods=["POST"])
def verify():

    try:
        image_data = base64.b64decode(request.json["image"].split(",")[1])

        with open("temp.jpg", "wb") as f:
            f.write(image_data)

        image = face_recognition.load_image_file("temp.jpg")
        encodings = face_recognition.face_encodings(image)

        os.remove("temp.jpg")

        if not encodings:
            return jsonify({"status": "No face detected"})

        if not known_face_encodings:
            return jsonify({"status": "No registered employees"})

        unknown_encoding = encodings[0]

        matches = face_recognition.compare_faces(known_face_encodings, unknown_encoding)
        distances = face_recognition.face_distance(known_face_encodings, unknown_encoding)

        if len(distances) == 0:
            return jsonify({"status": "No registered employees"})

        best_match_index = np.argmin(distances)

        if matches[best_match_index] and distances[best_match_index] < 0.45:

            emp_id = known_face_ids[best_match_index]
            emp_data = employees[emp_id]

            # Re-check Active Status
            master_records = employees_master_sheet.get_all_records()
            for record in master_records:
                if str(record["Emp_ID"]) == str(emp_id):
                    if record["Status"].strip().lower() != "active":
                        return jsonify({"status": "Employee not Active"})
                    break

            now = datetime.now()
            timestamp = now.strftime("%d/%m/%Y %H:%M:%S")

            excel_start = datetime(1899, 12, 30)
            attendance_date_number = (now - excel_start).days

            unique_key = f"{emp_id}_{attendance_date_number}"

            records = attendance_sheet.get_all_records()

            for record in records:
                if (
                    str(record["Employee ID"]) == str(emp_id)
                    and str(record["Attendance_Date"]) == str(attendance_date_number)
                ):
                    return jsonify({
                        "status": "ALREADY_MARKED",
                        "employee": emp_data["name"],
                        "emp_id": emp_id
                    })

            row = [
                timestamp,
                emp_data["email"],
                emp_data["name"],
                emp_id,
                emp_data["work_mode"],
                "",
                unique_key,
                attendance_date_number,
                "VALID"
            ]

            attendance_sheet.append_row(row)

            return jsonify({
                "status": "SUCCESS",
                "employee": emp_data["name"],
                "emp_id": emp_id
            })

        return jsonify({"status": "Face not recognized"})

    except Exception as e:
        return jsonify({"status": f"Attendance error: {str(e)}"})


# ==============================
# RUN APP (Gunicorn will use this)
# ==============================
if __name__ == "__main__":
    app.run()