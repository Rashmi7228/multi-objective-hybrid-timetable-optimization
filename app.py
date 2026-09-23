import os
import sqlite3
import secrets
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, session
from db import init_db, get_conn, hash_pw, DAYS, PERIODS, add_notification, get_notifications, get_break_meta, get_break_periods, set_break_config, find_teacher_conflict, find_class_conflict, find_room_conflict, find_classroom_conflict, find_class_record_conflict, TEACHER_UNAVAILABLE_MESSAGE, CLASS_UNAVAILABLE_MESSAGE, ROOM_UNAVAILABLE_MESSAGE, CLASSROOM_UNAVAILABLE_MESSAGE
from generator import generate_timetable_for_class
from datetime import datetime

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = os.environ.get("SESSION_SECRET", secrets.token_hex(32))

init_db()


def row_to_dict(row):
    return {k: row[k] for k in row.keys()} if row else None


def rows_to_list(rows):
    return [row_to_dict(r) for r in rows]


def require_role(role):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            # debug log
            try:
                print(f"require_role: needed={role}, session_role={session.get('role')}, user={session.get('user')}")
            except Exception:
                pass
            if session.get("role") != role:
                return jsonify({"error": "unauthorized"}), 401
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ---------- Static ----------
@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ---------- Meta ----------
@app.route("/api/meta")
def meta():
    return jsonify({
        "days": DAYS,
        "periods": PERIODS,
        "breaks": get_break_periods(),
        "breaks_meta": get_break_meta(),
    })


@app.route("/api/session")
def get_session():
    return jsonify({
        "role": session.get("role"),
        "user": session.get("user"),
        "user_id": session.get("user_id"),
    })


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})
# ---------- Auth ----------
@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    conn = get_conn()
    row = conn.execute("SELECT * FROM admins WHERE email = ?", (email,)).fetchone()
    conn.close()
    if not row or row["password_hash"] != hash_pw(password):
        return jsonify({"error": "Invalid email or password"}), 401
    session.clear()
    session["role"] = "admin"
    session["user"] = email
    session["user_id"] = row["id"]
    return jsonify({"ok": True, "user": email})


@app.route("/api/teacher/login", methods=["POST"])
def teacher_login():
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    passcode = data.get("passcode", "")
    conn = get_conn()
    row = conn.execute("SELECT * FROM teachers WHERE name = ?", (name,)).fetchone()
    conn.close()
    if not row or row["passcode_hash"] != hash_pw(passcode):
        return jsonify({"error": "Invalid name or passcode"}), 401
    session.clear()
    session["role"] = "teacher"
    session["user"] = name
    session["user_id"] = row["id"]
    return jsonify({"ok": True, "user": name})


# ---------- Student (no login) ----------
@app.route("/api/student/timetable")
def student_timetable():
    semester = request.args.get("semester", type=int)
    section = request.args.get("section", "").strip().upper()
    if not semester or not section:
        return jsonify({"error": "semester and section required"}), 400
    conn = get_conn()
    cls = conn.execute(
        "SELECT * FROM classes WHERE semester = ? AND section = ?",
        (semester, section),
    ).fetchone()
    if not cls:
        conn.close()
        return jsonify({"error": "Class not found"}), 404
    rows = conn.execute("""
        SELECT t.*, s.name AS subject_name, s.code AS subject_code, te.name AS teacher_name
        FROM timetable t
        LEFT JOIN subjects s ON s.id = t.subject_id
        LEFT JOIN teachers te ON te.id = t.teacher_id
        WHERE t.class_id = ?
        ORDER BY t.day, t.period
    """, (cls["id"],)).fetchall()
    conn.close()
    return jsonify({
        "class": row_to_dict(cls),
        "entries": rows_to_list(rows),
    })


@app.route("/api/student/notifications")
def student_notifications():
    semester = request.args.get("semester", type=int)
    section = request.args.get("section", "").strip().upper()
    target = f"{semester}-{section}" if semester and section else None
    rows = get_notifications("student", target)
    return jsonify({"items": rows_to_list(rows)})


@app.route("/api/classes")
def list_classes_public():
    conn = get_conn()
    rows = conn.execute("SELECT id, semester, section FROM classes ORDER BY semester, section").fetchall()
    conn.close()
    return jsonify({"items": rows_to_list(rows)})


# ---------- Teacher ----------
@app.route("/api/teacher/timetable")
@require_role("teacher")
def teacher_timetable():
    tid = session["user_id"]
    conn = get_conn()
    rows = conn.execute("""
        SELECT t.*, s.name AS subject_name, s.code AS subject_code,
               c.semester, c.section
        FROM timetable t
        LEFT JOIN subjects s ON s.id = t.subject_id
        LEFT JOIN classes c ON c.id = t.class_id
        WHERE t.teacher_id = ?
        ORDER BY t.day, t.period
    """, (tid,)).fetchall()
    conn.close()
    return jsonify({"entries": rows_to_list(rows)})


@app.route("/api/teacher/notifications")
@require_role("teacher")
def teacher_notifications():
    rows = get_notifications("teacher", session.get("user"))
    return jsonify({"items": rows_to_list(rows)})


@app.route("/api/teacher/action", methods=["POST"])
@require_role("teacher")
def teacher_action():
    data = request.get_json() or {}
    action = data.get("action")  # 'cancel', 'substitute', 'extra'
    entry_id = data.get("entry_id")
    note = data.get("note", "")
    substitute_teacher_id = data.get("substitute_teacher_id")

    conn = get_conn()
    if action == "cancel":
        entry = conn.execute("SELECT * FROM timetable WHERE id = ? AND teacher_id = ?",
                             (entry_id, session["user_id"])).fetchone()
        if not entry:
            conn.close()
            return jsonify({"error": "Entry not found"}), 404
        conn.execute("UPDATE timetable SET entry_type = 'cancelled', note = ? WHERE id = ?",
                     (note or "Cancelled by teacher", entry_id))
        conn.commit()
        conn.close()
        cls_target = f"{entry['class_id']}"
        # notify by class semester-section
        c2 = get_conn()
        cls = c2.execute("SELECT * FROM classes WHERE id = ?", (entry["class_id"],)).fetchone()
        c2.close()
        target = f"{cls['semester']}-{cls['section']}" if cls else None
        add_notification("student", target,
                         f"Class cancelled: {entry['day']} {entry['period']} ({session['user']}). {note}")
        return jsonify({"ok": True})

    elif action == "substitute":
        entry = conn.execute("SELECT * FROM timetable WHERE id = ? AND teacher_id = ?",
                             (entry_id, session["user_id"])).fetchone()
        if not entry:
            conn.close()
            return jsonify({"error": "Entry not found"}), 404
        if not substitute_teacher_id:
            conn.close()
            return jsonify({"error": "substitute_teacher_id required"}), 400
        sub = conn.execute("SELECT name FROM teachers WHERE id = ?", (substitute_teacher_id,)).fetchone()
        if find_teacher_conflict(conn, substitute_teacher_id, entry["day"], entry["period"], entry_id):
            conn.close()
            return jsonify({"error": TEACHER_UNAVAILABLE_MESSAGE}), 409
        conn.execute(
            "UPDATE timetable SET teacher_id = ?, entry_type = 'substitution', note = ? WHERE id = ?",
            (substitute_teacher_id, note or f"Substituted by {sub['name'] if sub else ''}", entry_id),
        )
        conn.commit()
        cls = conn.execute("SELECT * FROM classes WHERE id = ?", (entry["class_id"],)).fetchone()
        conn.close()
        target = f"{cls['semester']}-{cls['section']}" if cls else None
        add_notification("student", target,
                         f"Substitution: {entry['day']} {entry['period']} now taken by {sub['name'] if sub else 'TBA'}.")
        return jsonify({"ok": True})

    elif action == "extra":
        class_id = data.get("class_id")
        day = data.get("day")
        period = data.get("period")
        subject_id = data.get("subject_id")
        event_date = data.get("event_date")
        if not (class_id and day and period):
            conn.close()
            return jsonify({"error": "class_id, day, period required"}), 400
        if find_teacher_conflict(conn, session["user_id"], day, period):
            conn.close()
            return jsonify({"error": TEACHER_UNAVAILABLE_MESSAGE}), 409
        conn.execute("""
            INSERT INTO timetable (class_id, day, period, subject_id, teacher_id, entry_type, note, event_date)
            VALUES (?, ?, ?, ?, ?, 'extra', ?, ?)
        """, (class_id, day, period, subject_id, session["user_id"], note or "Extra class", event_date))
        conn.commit()
        cls = conn.execute("SELECT * FROM classes WHERE id = ?", (class_id,)).fetchone()
        conn.close()
        target = f"{cls['semester']}-{cls['section']}" if cls else None
        add_notification("student", target,
                         f"Extra class scheduled: {day} {period} by {session['user']}. {note}")
        return jsonify({"ok": True})

    conn.close()
    return jsonify({"error": "Unknown action"}), 400


@app.route("/api/teacher/colleagues")
@require_role("teacher")
def teacher_colleagues():
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, name FROM teachers WHERE id != ? ORDER BY name",
        (session["user_id"],),
    ).fetchall()
    conn.close()
    return jsonify({"items": rows_to_list(rows)})


@app.route("/api/teacher/own-classes")
@require_role("teacher")
def teacher_own_classes():
    conn = get_conn()
    rows = conn.execute("""
        SELECT DISTINCT c.id, c.semester, c.section
        FROM classes c
        JOIN timetable t ON t.class_id = c.id
        WHERE t.teacher_id = ?
        ORDER BY c.semester, c.section
    """, (session["user_id"],)).fetchall()
    conn.close()
    return jsonify({"items": rows_to_list(rows)})


# ---------- Teacher Leave endpoints ----------
@app.route("/api/teacher/leave/apply", methods=["POST"])
@require_role("teacher")
def teacher_leave_apply():
    d = request.get_json() or {}
    try:
        print("teacher_leave_apply called", session.get("role"), session.get("user"))
    except Exception:
        pass
    start_date = d.get("start_date")
    end_date = d.get("end_date") or start_date
    leave_type = d.get("leave_type", "Casual Leave")
    reason = d.get("reason", "")
    if not start_date:
        return jsonify({"error": "start_date required"}), 400
    conn = get_conn()
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO leaves (teacher_id, start_date, end_date, leave_type, reason, status, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?)",
        (session["user_id"], start_date, end_date, leave_type, reason, now),
    )
    conn.commit()
    teacher = session.get("user")
    conn.close()
    # notify admins
    add_notification("admin", None, f"New Leave Request Teacher: {teacher} Date: {start_date} - {end_date} Leave Type: {leave_type} Reason: {reason} Status: Pending")
    return jsonify({"ok": True})


@app.route("/api/teacher/leave/list")
@require_role("teacher")
def teacher_leave_list():
    tid = session["user_id"]
    try:
        print("teacher_leave_list called", session.get("role"), session.get("user"))
    except Exception:
        pass
    conn = get_conn()
    rows = conn.execute("SELECT * FROM leaves WHERE teacher_id = ? ORDER BY id DESC", (tid,)).fetchall()
    conn.close()
    return jsonify({"items": rows_to_list(rows)})


# ---------- Admin Leave endpoints ----------
@app.route("/api/admin/leaves")
@require_role("admin")
def admin_leaves_list():
    status = request.args.get("status")
    q = request.args.get("q", "").strip()
    conn = get_conn()
    sql = "SELECT l.*, t.name AS teacher_name FROM leaves l JOIN teachers t ON t.id = l.teacher_id"
    params = []
    clauses = []
    if status:
        clauses.append("l.status = ?"); params.append(status)
    if q:
        clauses.append("t.name LIKE ?"); params.append(f"%{q}%")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY l.id DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return jsonify({"items": rows_to_list(rows)})


def _day_name_from_iso(date_str: str):
    try:
        dt = datetime.fromisoformat(date_str)
        return dt.strftime("%A")
    except Exception:
        return None


@app.route("/api/admin/leaves/<int:lid>/affected")
@require_role("admin")
def admin_leave_affected(lid):
    conn = get_conn()
    leave = conn.execute("SELECT * FROM leaves WHERE id = ?", (lid,)).fetchone()
    if not leave:
        conn.close()
        return jsonify({"error": "Leave not found"}), 404
    # For now, compute affected entries by matching weekday names between start_date..end_date
    start = leave["start_date"]
    end = leave["end_date"] or start
    # Build set of day names
    s_dt = datetime.fromisoformat(start)
    e_dt = datetime.fromisoformat(end)
    days = set()
    cur = s_dt
    while cur.date() <= e_dt.date():
        days.add(cur.strftime("%A"))
        cur = cur + (e_dt - s_dt).replace(days=0) if False else cur.replace(day=cur.day)  # placeholder
        cur = cur + (e_dt - s_dt)  # fallback to break the loop if something weird
    # Simpler: just use start day
    days = {datetime.fromisoformat(start).strftime("%A")}
    # Find timetable entries for this teacher on these days
    rows = conn.execute("SELECT t.*, s.name AS subject_name, s.code AS subject_code, c.semester, c.section FROM timetable t LEFT JOIN subjects s ON s.id = t.subject_id LEFT JOIN classes c ON c.id = t.class_id WHERE t.teacher_id = ? AND t.day IN (" + ",".join(["?"]*len(days)) + ") ORDER BY t.day, t.period", (leave["teacher_id"],) + tuple(days)).fetchall()
    conn.close()
    return jsonify({"items": rows_to_list(rows), "days": list(days)})


@app.route("/api/admin/leaves/<int:lid>/decide", methods=["POST"])
@require_role("admin")
def admin_leave_decide(lid):
    d = request.get_json() or {}
    action = d.get("action")  # 'approve' or 'reject'
    note = d.get("note", "")
    conn = get_conn()
    leave = conn.execute("SELECT * FROM leaves WHERE id = ?", (lid,)).fetchone()
    if not leave:
        conn.close()
        return jsonify({"error": "Leave not found"}), 404
    now = datetime.now().isoformat(timespec="seconds")
    if action == "approve":
        conn.execute("UPDATE leaves SET status = 'approved', admin_note = ?, updated_at = ? WHERE id = ?", (note, now, lid))
        conn.commit()
        teacher = conn.execute("SELECT name FROM teachers WHERE id = ?", (leave["teacher_id"],)).fetchone()
        conn.close()
        add_notification("teacher", teacher["name"] if teacher else None, f"Your leave request ({leave['start_date']}) was approved.")
        add_notification("admin", None, f"Leave approved for {teacher['name'] if teacher else ''} {leave['start_date']}")
        return jsonify({"ok": True})
    elif action == "reject":
        conn.execute("UPDATE leaves SET status = 'rejected', admin_note = ?, updated_at = ? WHERE id = ?", (note, now, lid))
        conn.commit()
        teacher = conn.execute("SELECT name FROM teachers WHERE id = ?", (leave["teacher_id"],)).fetchone()
        conn.close()
        add_notification("teacher", teacher["name"] if teacher else None, f"Your leave request ({leave['start_date']}) was rejected. Reason: {note}")
        return jsonify({"ok": True})
    conn.close()
    return jsonify({"error": "invalid action"}), 400


@app.route("/api/admin/leaves/<int:lid>/assign", methods=["POST"])
@require_role("admin")
def admin_leave_assign(lid):
    d = request.get_json() or {}
    assignments = d.get("assignments", [])
    # assignments: [{class_id, day, period, substitute_teacher_id}]
    conn = get_conn()
    leave = conn.execute("SELECT * FROM leaves WHERE id = ?", (lid,)).fetchone()
    if not leave:
        conn.close()
        return jsonify({"error": "Leave not found"}), 404
    for a in assignments:
        class_id = a.get("class_id")
        day = a.get("day")
        period = a.get("period")
        sub_tid = a.get("substitute_teacher_id")
        if not (class_id and day and period and sub_tid):
            continue
        if find_teacher_conflict(conn, sub_tid, day, period):
            conn.close()
            return jsonify({"error": TEACHER_UNAVAILABLE_MESSAGE}), 409
        # Update timetable entries that match
        conn.execute("UPDATE timetable SET teacher_id = ?, entry_type = 'substitution', note = ? WHERE class_id = ? AND day = ? AND period = ? AND teacher_id = ?",
                     (sub_tid, f"Substitute for leave {lid}", class_id, day, period, leave["teacher_id"]))
    conn.commit()
    # notify teacher and substitutes
    teacher = conn.execute("SELECT name FROM teachers WHERE id = ?", (leave["teacher_id"],)).fetchone()
    conn.close()
    add_notification("teacher", teacher["name"] if teacher else None, f"Substitutes assigned for your leave starting {leave['start_date']}")
    add_notification("admin", None, f"Substitutes assigned for leave {lid}")
    return jsonify({"ok": True})


# ---------- Admin ----------
@app.route("/api/admin/teachers", methods=["GET", "POST"])
@require_role("admin")
def admin_teachers():
    conn = get_conn()
    if request.method == "POST":
        d = request.get_json() or {}
        name = d.get("name", "").strip()
        passcode = d.get("passcode", "")
        email = d.get("email", "").strip()
        if not name or not passcode:
            return jsonify({"error": "name and passcode required"}), 400
        try:
            conn.execute(
                "INSERT INTO teachers (name, passcode_hash, email) VALUES (?, ?, ?)",
                (name, hash_pw(passcode), email),
            )
            conn.commit()
        except Exception as e:
            conn.close()
            return jsonify({"error": str(e)}), 400
        conn.close()
        return jsonify({"ok": True})
    rows = conn.execute("SELECT id, name, email FROM teachers ORDER BY name").fetchall()
    conn.close()
    return jsonify({"items": rows_to_list(rows)})


@app.route("/api/admin/teachers/<int:tid>", methods=["DELETE", "PUT"])
@require_role("admin")
def admin_teacher_modify(tid):
    conn = get_conn()
    if request.method == "DELETE":
        if not conn.execute("SELECT 1 FROM teachers WHERE id = ?", (tid,)).fetchone():
            conn.close()
            return jsonify({"error": "Teacher not found."}), 404
        if conn.execute("SELECT 1 FROM timetable WHERE teacher_id = ? LIMIT 1", (tid,)).fetchone():
            conn.close()
            return jsonify({"error": "Cannot delete this teacher because they are assigned to existing timetable entries."}), 409
        if conn.execute("SELECT 1 FROM subject_assignments WHERE teacher_id = ? LIMIT 1", (tid,)).fetchone():
            conn.close()
            return jsonify({"error": "Cannot delete this teacher because they are assigned to subjects."}), 409
        if conn.execute("SELECT 1 FROM subjects WHERE teacher_id = ? LIMIT 1", (tid,)).fetchone():
            conn.close()
            return jsonify({"error": "Cannot delete this teacher because they are assigned to subjects."}), 409
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'leaves'").fetchone() and conn.execute("SELECT 1 FROM leaves WHERE teacher_id = ? LIMIT 1", (tid,)).fetchone():
            conn.close()
            return jsonify({"error": "Cannot delete this teacher because they have existing leave records."}), 409
        conn.execute("DELETE FROM teachers WHERE id = ?", (tid,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    d = request.get_json() or {}
    fields, vals = [], []
    if "name" in d:
        fields.append("name = ?"); vals.append(d["name"])
    if "email" in d:
        fields.append("email = ?"); vals.append(d["email"])
    if d.get("passcode"):
        fields.append("passcode_hash = ?"); vals.append(hash_pw(d["passcode"]))
    if not fields:
        conn.close()
        return jsonify({"error": "no changes"}), 400
    vals.append(tid)
    conn.execute(f"UPDATE teachers SET {', '.join(fields)} WHERE id = ?", vals)
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/admin/subjects", methods=["GET", "POST"])
@require_role("admin")
def admin_subjects():
    conn = get_conn()
    if request.method == "POST":
        d = request.get_json() or {}
        code = str(d.get("code", "")).strip()
        name = str(d.get("name", "")).strip()
        if not code or not name:
            conn.close()
            return jsonify({"error": "code and name required"}), 400
        try:
            assignments = validate_subject_assignments(conn, d.get("assignments"))
            legacy_assignment = assignments[0] if assignments else None
            conn.execute(
                "INSERT INTO subjects (code, name, teacher_id, semester, weekly_hours) VALUES (?, ?, ?, ?, ?)",
                (code, name,
                 legacy_assignment["teacher_id"] if legacy_assignment else d.get("teacher_id"),
                 legacy_assignment["semester"] if legacy_assignment else int(d.get("semester", 1)),
                 int(d.get("weekly_hours", 3))),
            )
            subject_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.executemany(
                "INSERT INTO subject_assignments (subject_id, semester, section, teacher_id) VALUES (?, ?, ?, ?)",
                [(subject_id, a["semester"], a["section"], a["teacher_id"]) for a in assignments],
            )
            conn.commit()
        except Exception as e:
            conn.close()
            return jsonify({"error": str(e)}), 400
        conn.close()
        return jsonify({"ok": True})
    rows = conn.execute("SELECT * FROM subjects ORDER BY semester, code").fetchall()
    assignments = conn.execute("""
        SELECT sa.*, t.name AS teacher_name
        FROM subject_assignments sa
        JOIN teachers t ON t.id = sa.teacher_id
        ORDER BY sa.semester, sa.section, t.name
    """).fetchall()
    conn.close()
    items = rows_to_list(rows)
    assignment_map = {}
    for assignment in assignments:
        assignment_map.setdefault(assignment["subject_id"], []).append(row_to_dict(assignment))
    for item in items:
        item["assignments"] = assignment_map.get(item["id"], [])
    return jsonify({"items": items})


def validate_subject_assignments(conn, raw_assignments):
    if raw_assignments is None:
        return []
    if not isinstance(raw_assignments, list):
        raise ValueError("assignments must be a list")
    cleaned = []
    seen = set()
    for assignment in raw_assignments:
        if not isinstance(assignment, dict):
            raise ValueError("invalid subject assignment")
        section = str(assignment.get("section", "")).strip().upper()
        if not section:
            raise ValueError("assignment section required")
        try:
            semester = int(assignment.get("semester"))
            teacher_id = int(assignment.get("teacher_id"))
        except (TypeError, ValueError):
            raise ValueError("assignment semester and teacher are required")
        if semester < 1:
            raise ValueError("assignment semester must be positive")
        if (semester, section) in seen:
            raise ValueError("duplicate subject assignment")
        if not conn.execute("SELECT 1 FROM teachers WHERE id = ?", (teacher_id,)).fetchone():
            raise ValueError("assignment teacher not found")
        seen.add((semester, section))
        cleaned.append({"semester": semester, "section": section, "teacher_id": teacher_id})
    return cleaned


@app.route("/api/admin/subjects/<int:sid>", methods=["DELETE", "PUT"])
@require_role("admin")
def admin_subject_modify(sid):
    conn = get_conn()
    if request.method == "DELETE":
        if not conn.execute("SELECT 1 FROM subjects WHERE id = ?", (sid,)).fetchone():
            conn.close()
            return jsonify({"error": "Subject not found."}), 404
        if conn.execute("SELECT 1 FROM timetable WHERE subject_id = ? LIMIT 1", (sid,)).fetchone():
            conn.close()
            return jsonify({"error": "Cannot delete this subject because it is used by existing timetable entries."}), 409
        if conn.execute("SELECT 1 FROM subject_assignments WHERE subject_id = ? LIMIT 1", (sid,)).fetchone():
            conn.close()
            return jsonify({"error": "Cannot delete this subject because it has semester or section assignments."}), 409
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    d = request.get_json() or {}
    code = str(d.get("code", "")).strip()
    name = str(d.get("name", "")).strip()
    if not code or not name:
        conn.close()
        return jsonify({"error": "code and name required"}), 400
    try:
        assignments = validate_subject_assignments(conn, d.get("assignments"))
        legacy_assignment = assignments[0] if assignments else None
        cursor = conn.execute("""
            UPDATE subjects SET code = ?, name = ?, teacher_id = ?, semester = ?, weekly_hours = ?
            WHERE id = ?
        """, (code, name,
              legacy_assignment["teacher_id"] if legacy_assignment else d.get("teacher_id"),
              legacy_assignment["semester"] if legacy_assignment else int(d.get("semester", 1)),
              int(d.get("weekly_hours", 3)), sid))
        if cursor.rowcount == 0:
            conn.close()
            return jsonify({"error": "Subject not found"}), 404
        conn.execute("DELETE FROM subject_assignments WHERE subject_id = ?", (sid,))
        conn.executemany(
            "INSERT INTO subject_assignments (subject_id, semester, section, teacher_id) VALUES (?, ?, ?, ?)",
            [(sid, a["semester"], a["section"], a["teacher_id"]) for a in assignments],
        )
        conn.commit()
    except (TypeError, ValueError) as e:
        conn.rollback()
        conn.close()
        return jsonify({"error": str(e) or "semester and weekly_hours must be numbers"}), 400
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({"error": str(e)}), 400
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/admin/classes", methods=["GET", "POST"])
@require_role("admin")
def admin_classes():
    conn = get_conn()
    if request.method == "POST":
        d = request.get_json() or {}
        semester = int(d.get("semester", 1))
        section = d.get("section", "").strip().upper()
        room = d.get("room", "").strip()
        existing_class = find_class_record_conflict(conn, semester, section)
        if existing_class:
            conn.close()
            return jsonify({
                "error": f"Class Already Exists: Semester {semester} Section {section} is already assigned to Room {existing_class['room'] or '—'}."
            }), 409
        existing_room = find_classroom_conflict(conn, room)
        if existing_room:
            conn.close()
            return jsonify({
                "error": f"Classroom Unavailable: Room {room} is already assigned to Semester {existing_room['semester']} Section {existing_room['section']}."
            }), 409
        try:
            conn.execute(
                "INSERT INTO classes (semester, section, room) VALUES (?, ?, ?)",
                (semester, section, room),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            existing_class = find_class_record_conflict(conn, semester, section)
            existing_room = find_classroom_conflict(conn, room)
            conn.close()
            if existing_class:
                return jsonify({
                    "error": f"Class Already Exists: Semester {semester} Section {section} is already assigned to Room {existing_class['room'] or '—'}."
                }), 409
            if existing_room:
                return jsonify({
                    "error": f"Classroom Unavailable: Room {room} is already assigned to Semester {existing_room['semester']} Section {existing_room['section']}."
                }), 409
            return jsonify({"error": "Unable to save class. Please try again."}), 409
        except Exception as e:
            conn.close()
            return jsonify({"error": str(e)}), 400
        conn.close()
        return jsonify({"ok": True})
    rows = conn.execute("SELECT * FROM classes ORDER BY semester, section").fetchall()
    conn.close()
    return jsonify({"items": rows_to_list(rows)})


@app.route("/api/admin/classes/<int:cid>", methods=["PUT", "DELETE"])
@require_role("admin")
def admin_class_delete(cid):
    conn = get_conn()
    if not conn.execute("SELECT 1 FROM classes WHERE id = ?", (cid,)).fetchone():
        conn.close()
        return jsonify({"error": "Class not found."}), 404
    if request.method == "PUT":
        d = request.get_json() or {}
        semester = int(d.get("semester", 1))
        section = d.get("section", "").strip().upper()
        room = d.get("room", "").strip()
        existing_class = find_class_record_conflict(conn, semester, section, cid)
        if existing_class:
            conn.close()
            return jsonify({
                "error": f"Class Already Exists: Semester {semester} Section {section} is already assigned to Room {existing_class['room'] or '—'}."
            }), 409
        existing_room = find_classroom_conflict(conn, room, cid)
        if existing_room:
            conn.close()
            return jsonify({
                "error": f"Classroom Unavailable: Room {room} is already assigned to Semester {existing_room['semester']} Section {existing_room['section']}."
            }), 409
        try:
            conn.execute(
                "UPDATE classes SET semester = ?, section = ?, room = ? WHERE id = ?",
                (semester, section, room, cid),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            existing_class = find_class_record_conflict(conn, semester, section, cid)
            existing_room = find_classroom_conflict(conn, room, cid)
            conn.close()
            if existing_class:
                return jsonify({
                    "error": f"Class Already Exists: Semester {semester} Section {section} is already assigned to Room {existing_class['room'] or '—'}."
                }), 409
            if existing_room:
                return jsonify({
                    "error": f"Classroom Unavailable: Room {room} is already assigned to Semester {existing_room['semester']} Section {existing_room['section']}."
                }), 409
            return jsonify({"error": "Unable to update class. Please try again."}), 409
        conn.close()
        return jsonify({"ok": True})
    if conn.execute("SELECT 1 FROM timetable WHERE class_id = ? LIMIT 1", (cid,)).fetchone():
        conn.close()
        return jsonify({"error": "Cannot delete this class because it has existing timetable entries."}), 409
    conn.execute("DELETE FROM classes WHERE id = ?", (cid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/admin/timetable")
@require_role("admin")
def admin_timetable():
    class_id = request.args.get("class_id", type=int)
    if not class_id:
        return jsonify({"error": "class_id required"}), 400
    day = request.args.get("day")
    period = request.args.get("period")
    conn = get_conn()
    sql = """
        SELECT t.*, s.name AS subject_name, s.code AS subject_code, te.name AS teacher_name
        FROM timetable t
        LEFT JOIN subjects s ON s.id = t.subject_id
        LEFT JOIN teachers te ON te.id = t.teacher_id
        WHERE t.class_id = ?
    """
    params = [class_id]
    if day:
        sql += " AND t.day = ?"
        params.append(day)
    if period:
        sql += " AND t.period = ?"
        params.append(period)
    sql += " ORDER BY t.day, t.period"
    rows = conn.execute(sql, params).fetchall()
    cls = conn.execute("SELECT * FROM classes WHERE id = ?", (class_id,)).fetchone()
    conn.close()
    entries = rows_to_list(rows)
    return jsonify({"class": row_to_dict(cls), "entries": entries, "items": entries})


@app.route("/api/admin/breaks", methods=["GET", "PUT"])
@require_role("admin")
def admin_breaks():
    if request.method == "GET":
        return jsonify({"items": get_break_meta()})
    data = request.get_json() or {}
    breaks = data.get("breaks") or []
    cleaned = []
    for item in breaks:
        label = (item.get("label") or "BREAK").strip().upper()
        start = str(item.get("start") or "").strip()
        end = str(item.get("end") or start).strip()
        if not start:
            continue
        cleaned.append({"start": start, "end": end, "label": label})
    if not cleaned:
        return jsonify({"error": "at least one break is required"}), 400
    set_break_config(cleaned)
    return jsonify({"ok": True, "items": get_break_meta()})


@app.route("/api/admin/timetable/generate", methods=["POST"])
@require_role("admin")
def admin_generate():
    d = request.get_json() or {}
    class_id = d.get("class_id")
    if not class_id:
        return jsonify({"error": "class_id required"}), 400
    ok, msg = generate_timetable_for_class(int(class_id))
    if not ok and msg in (TEACHER_UNAVAILABLE_MESSAGE, CLASS_UNAVAILABLE_MESSAGE, ROOM_UNAVAILABLE_MESSAGE):
        return jsonify({"error": msg}), 409
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/admin/timetable/entry", methods=["POST", "PUT", "DELETE"])
@require_role("admin")
def admin_entry():
    d = request.get_json() or {}
    conn = get_conn()
    if request.method == "POST":
        entries = d.get("entries") if isinstance(d.get("entries"), list) else [d]
        if not entries:
            conn.close()
            return jsonify({"error": "At least one timetable entry is required."}), 400

        break_periods = get_break_periods()
        seen_teacher_slots = set()
        seen_class_slots = set()
        seen_room_slots = set()
        prepared = []
        for entry in entries:
            period = entry.get("period")
            if period in break_periods:
                conn.close()
                return jsonify({"error": "Cannot add entries during break periods."}), 400
            class_id = entry.get("class_id")
            day = entry.get("day")
            assignment_teacher_id = subject_teacher_for_class(conn, entry.get("subject_id"), class_id)
            teacher_id = assignment_teacher_id if assignment_teacher_id is not None else entry.get("teacher_id")
            room = entry.get("room")
            teacher_slot = (teacher_id, day, period)
            class_slot = (class_id, day, period)
            room_slot = (room, day, period)

            if find_teacher_conflict(conn, teacher_id, day, period) or (teacher_id and teacher_slot in seen_teacher_slots):
                conn.close()
                return jsonify({"error": TEACHER_UNAVAILABLE_MESSAGE}), 409
            if find_class_conflict(conn, class_id, day, period) or (class_id and class_slot in seen_class_slots):
                conn.close()
                return jsonify({"error": CLASS_UNAVAILABLE_MESSAGE}), 409
            if find_room_conflict(conn, room, day, period) or (room and str(room).strip() and room_slot in seen_room_slots):
                conn.close()
                return jsonify({"error": ROOM_UNAVAILABLE_MESSAGE}), 409

            if teacher_id:
                seen_teacher_slots.add(teacher_slot)
            if class_id:
                seen_class_slots.add(class_slot)
            if room and str(room).strip():
                seen_room_slots.add(room_slot)
            prepared.append((
                class_id, day, period, entry.get("subject_id"), teacher_id, room,
                entry.get("entry_type"), entry.get("note"), entry.get("locked"),
            ))

        conn.executemany("""
            INSERT INTO timetable (class_id, day, period, subject_id, teacher_id, room, entry_type, note, locked)
            VALUES (?, ?, ?, ?, ?, ?, COALESCE(?, 'regular'), ?, COALESCE(?, 0))
        """, prepared)
        conn.commit()
        cls = conn.execute("SELECT * FROM classes WHERE id = ?", (prepared[0][0],)).fetchone()
        conn.close()
        if cls:
            add_notification("student", f"{cls['semester']}-{cls['section']}", "Timetable updated by admin.")
        return jsonify({"ok": True})
    if request.method == "PUT":
        eid = d.get("id")
        period = d.get("period")
        if period in get_break_periods():
            conn.close()
            return jsonify({"error": "Cannot set break periods as admin entries."}), 400
        assignment_teacher_id = subject_teacher_for_class(conn, d.get("subject_id"), d.get("class_id"))
        teacher_id = assignment_teacher_id if assignment_teacher_id is not None else d.get("teacher_id")
        if find_teacher_conflict(conn, teacher_id, d.get("day"), period, eid):
            conn.close()
            return jsonify({"error": TEACHER_UNAVAILABLE_MESSAGE}), 409
        if find_class_conflict(conn, d.get("class_id"), d.get("day"), period, eid):
            conn.close()
            return jsonify({"error": CLASS_UNAVAILABLE_MESSAGE}), 409
        if find_room_conflict(conn, d.get("room"), d.get("day"), period, eid):
            conn.close()
            return jsonify({"error": ROOM_UNAVAILABLE_MESSAGE}), 409
        # Prevent modifying locked entries unless explicitly allowed by admin: front-end may toggle locked flag
        conn.execute("""
            UPDATE timetable SET day = ?, period = ?, subject_id = ?, teacher_id = ?,
                room = ?, entry_type = ?, note = ?, locked = COALESCE(?, locked) WHERE id = ?
        """, (d.get("day"), period, d.get("subject_id"), teacher_id,
              d.get("room"), d.get("entry_type", "regular"), d.get("note"), d.get("locked"), eid))
        conn.commit()
        ent = conn.execute("SELECT class_id FROM timetable WHERE id = ?", (eid,)).fetchone()
        cls = conn.execute("SELECT * FROM classes WHERE id = ?", (ent["class_id"],)).fetchone() if ent else None
        conn.close()
        if cls:
            add_notification("student", f"{cls['semester']}-{cls['section']}", "Timetable modified by admin.")
        return jsonify({"ok": True})
    if request.method == "DELETE":
        eid = d.get("id")
        ent = conn.execute("SELECT class_id, locked FROM timetable WHERE id = ?", (eid,)).fetchone()
        if not ent:
            conn.close()
            return jsonify({"error": "Timetable entry not found."}), 404
        if ent and ent["locked"]:
            conn.close()
            return jsonify({"error": "Entry is locked and cannot be deleted."}), 423
        conn.execute("DELETE FROM timetable WHERE id = ?", (eid,))
        conn.commit()
        cls = conn.execute("SELECT * FROM classes WHERE id = ?", (ent["class_id"],)).fetchone() if ent else None
        conn.close()
        if cls:
            add_notification("student", f"{cls['semester']}-{cls['section']}", "An entry was removed from your timetable.")
        return jsonify({"ok": True})
    conn.close()
    return jsonify({"error": "bad request"}), 400


def subject_teacher_for_class(conn, subject_id, class_id):
    if not subject_id or not class_id:
        return None
    return_value = conn.execute("""
        SELECT sa.teacher_id
        FROM subject_assignments sa
        JOIN classes c ON c.semester = sa.semester AND c.section = sa.section
        WHERE sa.subject_id = ? AND c.id = ?
    """, (subject_id, class_id)).fetchone()
    return return_value["teacher_id"] if return_value else None


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # Print registered routes for debugging
    try:
        print("Registered routes:")
        for rule in app.url_map.iter_rules():
            print(rule)
    except Exception:
        pass
    app.run(host="0.0.0.0", port=port, debug=False)
