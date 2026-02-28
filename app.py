from flask import Flask, render_template, request, jsonify
from deepface import DeepFace
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
# REGISTER FACE (DeepFace)
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

        # 🔐 Validate from Employees_Master
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

        # Save image temporarily
        temp_path = f"temp_{emp_id}.jpg"
        with open(temp_path, "wb") as f:
            f.write(image_data)

        # Generate embedding
        embedding = DeepFace.represent(
            img_path=temp_path,
            model_name="Facenet",
            enforce_detection=True
        )[0]["embedding"]

        os.remove(temp_path)

        # Store embedding in JSON
        employees[emp_id] = {
            "name": employee_record["Name"],
            "email": employee_record["Email"],
            "work_mode": work_mode,
            "embedding": embedding
        }

        with open("employees.json", "w") as f:
            json.dump(employees, f)

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

        if not employees:
            return jsonify({"status": "No registered employees"})

        temp_path = "temp_verify.jpg"
        with open(temp_path, "wb") as f:
            f.write(image_data)

        # Generate embedding for incoming face
        unknown_embedding = DeepFace.represent(
            img_path=temp_path,
            model_name="Facenet",
            enforce_detection=True
        )[0]["embedding"]

        os.remove(temp_path)

        best_match_id = None
        best_distance = 999

        # Compare embeddings manually (cosine distance)
        from numpy import dot
        from numpy.linalg import norm

        for emp_id, data in employees.items():

            stored_embedding = data["embedding"]

            cosine_distance = 1 - (
                dot(unknown_embedding, stored_embedding)
                / (norm(unknown_embedding) * norm(stored_embedding))
            )

            if cosine_distance < best_distance:
                best_distance = cosine_distance
                best_match_id = emp_id

        # Threshold (tuned for Facenet)
        if best_distance > 0.4:
            return jsonify({"status": "Face not recognized"})

        emp_id = best_match_id
        emp_data = employees[emp_id]

        # 🔐 Re-check Active Status
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

        # 🚨 STRICT duplicate prevention
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

    except Exception as e:
        return jsonify({"status": f"Attendance error: {str(e)}"})


# ==============================
# RUN APP
# ==============================
if __name__ == "__main__":
    app.run()