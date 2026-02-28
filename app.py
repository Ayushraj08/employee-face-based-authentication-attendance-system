import os
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

from flask import Flask, render_template, request, jsonify
from deepface import DeepFace
import json
from datetime import datetime
import base64
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import numpy as np

# ==============================
# APP CONFIG
# ==============================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

# ==============================
# LOAD REGISTERED EMPLOYEES
# ==============================
if os.path.exists("employees.json") and os.path.getsize("employees.json") > 0:
    with open("employees.json") as f:
        employees = json.load(f)
else:
    employees = {}

# ==============================
# GOOGLE SHEETS SETUP
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
# REGISTER FACE
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

        # Validate employee
        master_records = employees_master_sheet.get_all_records()
        employee_record = next(
            (r for r in master_records if str(r["Emp_ID"]) == str(emp_id)), None
        )

        if not employee_record:
            return jsonify({"status": "Emp_ID not found in Employees_Master"})

        if employee_record["Status"].strip().lower() != "active":
            return jsonify({"status": "Employee is not Active"})

        if emp_id in employees:
            return jsonify({
                "status": "ALREADY_REGISTERED",
                "employee": employees[emp_id]["name"]
            })

        temp_path = f"temp_{emp_id}.jpg"
        with open(temp_path, "wb") as f:
            f.write(image_data)

        representation = DeepFace.represent(
            img_path=temp_path,
            model_name="Facenet",
            detector_backend="opencv",
            enforce_detection=False
        )

        os.remove(temp_path)

        embedding = representation[0]["embedding"]

        employees[emp_id] = {
            "name": employee_record["Name"],
            "email": employee_record["Email"],
            "work_mode": work_mode,
            "embedding": list(map(float, embedding))
        }

        with open("employees.json", "w") as f:
            json.dump(employees, f, indent=4)

        return jsonify({
            "status": "REGISTERED",
            "employee": employee_record["Name"]
        })

    except Exception as e:
        return jsonify({"status": f"Registration error: {str(e)}"})

# ==============================
# VERIFY FACE
# ==============================
@app.route("/verify", methods=["POST"])
def verify():
    try:
        if not employees:
            return jsonify({"status": "No registered employees"})

        image_data = base64.b64decode(request.json["image"].split(",")[1])

        temp_path = "temp_verify.jpg"
        with open(temp_path, "wb") as f:
            f.write(image_data)

        representation = DeepFace.represent(
            img_path=temp_path,
            model_name="Facenet",
            detector_backend="opencv",
            enforce_detection=False
        )

        os.remove(temp_path)

        unknown_embedding = np.array(representation[0]["embedding"])

        best_match_id = None
        best_distance = 999

        for emp_id, data in employees.items():
            stored_embedding = np.array(data["embedding"])

            cosine_distance = 1 - (
                np.dot(unknown_embedding, stored_embedding)
                / (np.linalg.norm(unknown_embedding) * np.linalg.norm(stored_embedding))
            )

            if cosine_distance < best_distance:
                best_distance = cosine_distance
                best_match_id = emp_id

        if best_distance > 0.4:
            return jsonify({"status": "Face not recognized"})

        emp_data = employees[best_match_id]

        # Re-check Active Status
        master_records = employees_master_sheet.get_all_records()
        record = next(
            (r for r in master_records if str(r["Emp_ID"]) == str(best_match_id)), None
        )

        if not record or record["Status"].strip().lower() != "active":
            return jsonify({"status": "Employee not Active"})

        now = datetime.now()
        timestamp = now.strftime("%d/%m/%Y %H:%M:%S")

        excel_start = datetime(1899, 12, 30)
        attendance_date_number = (now - excel_start).days

        unique_key = f"{best_match_id}_{attendance_date_number}"

        records = attendance_sheet.get_all_records()

        for r in records:
            if (
                str(r["Employee ID"]) == str(best_match_id)
                and str(r["Attendance_Date"]) == str(attendance_date_number)
            ):
                return jsonify({
                    "status": "ALREADY_MARKED",
                    "employee": emp_data["name"],
                    "emp_id": best_match_id
                })

        row = [
            timestamp,
            emp_data["email"],
            emp_data["name"],
            best_match_id,
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
            "emp_id": best_match_id
        })

    except Exception as e:
        return jsonify({"status": f"Attendance error: {str(e)}"})

# ==============================
# RUN
# ==============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)