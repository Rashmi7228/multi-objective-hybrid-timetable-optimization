import sqlite3
import hashlib
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "timetable.db"

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
# Periods set to match the requested schedule. Break periods are included as
# explicit period labels so they can be treated as unavailable for teaching
# and rendered as distinct break cells in the UI.
PERIODS = [
    "09:00–09:55",
    "09:55–10:50",
    "10:50–11:00",
    "11:00–11:55",
    "11:55–12:50",
    "12:50–01:30",
    "01:30–02:20",
    "02:20–03:10",
    "03:10–04:00",
]

# Break configuration. Each entry defines the start and end timetable period,
# the label shown to users, and any periods it spans. The app automatically
# computes the colspan and excludes all covered periods from teaching slots.
BREAK_CONFIG = [
    {"start": "10:50–11:00", "end": "10:50–11:00", "label": "SHORT BREAK"},
    {"start": "12:50–01:30", "end": "12:50–01:30", "label": "LUNCH BREAK"},
]


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


TEACHER_UNAVAILABLE_MESSAGE = "Teacher Unavailable: This teacher is already assigned to another class during this time."
CLASS_UNAVAILABLE_MESSAGE = "Class Unavailable: This class already has a timetable entry during this time."
ROOM_UNAVAILABLE_MESSAGE = "Room Unavailable: This room is already assigned to another class during this time."
CLASSROOM_UNAVAILABLE_MESSAGE = "Classroom Unavailable: This classroom is already assigned to another class."


def find_class_record_conflict(conn, semester, section, exclude_id=None):
    sql = "SELECT id, semester, section, room FROM classes WHERE semester = ? AND section = ?"
    params = [semester, section]
    if exclude_id is not None:
        sql += " AND id != ?"
        params.append(exclude_id)
    return conn.execute(sql + " LIMIT 1", params).fetchone()


def find_teacher_conflict(conn, teacher_id, day, period, exclude_id=None):
    if not teacher_id or not day or not period:
        return None
    sql = """
        SELECT id
        FROM timetable
        WHERE teacher_id = ?
          AND day = ?
          AND period = ?
          AND COALESCE(entry_type, 'regular') != 'cancelled'
    """
    params = [teacher_id, day, period]
    if exclude_id is not None:
        sql += " AND id != ?"
        params.append(exclude_id)
    return conn.execute(sql, params).fetchone()


def find_class_conflict(conn, class_id, day, period, exclude_id=None):
    if not class_id or not day or not period:
        return None
    sql = """
        SELECT id
        FROM timetable
        WHERE class_id = ?
          AND day = ?
          AND period = ?
          AND COALESCE(entry_type, 'regular') != 'cancelled'
    """
    params = [class_id, day, period]
    if exclude_id is not None:
        sql += " AND id != ?"
        params.append(exclude_id)
    return conn.execute(sql, params).fetchone()


def find_room_conflict(conn, room, day, period, exclude_id=None):
    if not room or not str(room).strip() or not day or not period:
        return None
    sql = """
        SELECT id
        FROM timetable
        WHERE room = ?
          AND day = ?
          AND period = ?
          AND COALESCE(entry_type, 'regular') != 'cancelled'
    """
    params = [room, day, period]
    if exclude_id is not None:
        sql += " AND id != ?"
        params.append(exclude_id)
    return conn.execute(sql, params).fetchone()


def find_classroom_conflict(conn, room, exclude_id=None):
    if not room or not str(room).strip():
        return None
    sql = "SELECT id, semester, section, room FROM classes WHERE room = ?"
    params = [str(room).strip()]
    if exclude_id is not None:
        sql += " AND id != ?"
        params.append(exclude_id)
    sql += " LIMIT 1"
    return conn.execute(sql, params).fetchone()


def get_break_config(periods=None):
    periods = periods or PERIODS
    try:
        conn = get_conn()
        rows = conn.execute(
            "SELECT start_time, end_time, label FROM break_settings ORDER BY id"
        ).fetchall()
        conn.close()
    except sqlite3.OperationalError:
        return BREAK_CONFIG
    if rows:
        return [
            {
                "start": row["start_time"],
                "end": row["end_time"],
                "label": row["label"],
            }
            for row in rows
            if row["start_time"] in periods
        ] or BREAK_CONFIG
    return BREAK_CONFIG


def set_break_config(breaks):
    conn = get_conn()
    conn.execute("DELETE FROM break_settings")
    for item in breaks or []:
        label = (item.get("label") or "BREAK").strip().upper()
        start = str(item.get("start") or "").strip()
        end = str(item.get("end") or start).strip()
        if not start:
            continue
        conn.execute(
            "INSERT INTO break_settings (start_time, end_time, label) VALUES (?, ?, ?)",
            (start, end, label),
        )
    conn.commit()
    conn.close()
    return get_break_config()


def get_break_periods(periods=None):
    periods = periods or PERIODS
    config = get_break_config(periods)
    result = {}
    for break_def in config:
        start_idx = periods.index(break_def["start"]) if break_def["start"] in periods else -1
        end_idx = periods.index(break_def["end"]) if break_def["end"] in periods else start_idx
        if start_idx < 0:
            continue
        span_start = min(start_idx, end_idx)
        span_end = max(start_idx, end_idx)
        for idx in range(span_start, span_end + 1):
            result[periods[idx]] = break_def["label"]
    return result


BREAK_PERIODS = get_break_periods()


def get_break_meta(periods=None):
    periods = periods or PERIODS
    config = get_break_config(periods)
    meta = []
    for break_def in config:
        start_idx = periods.index(break_def["start"]) if break_def["start"] in periods else -1
        end_idx = periods.index(break_def["end"]) if break_def["end"] in periods else start_idx
        if start_idx < 0:
            continue
        span = max(1, abs(end_idx - start_idx) + 1)
        meta.append({
            "start": break_def["start"],
            "end": break_def["end"],
            "label": break_def["label"],
            "span": span,
        })
    return meta


def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            passcode_hash TEXT NOT NULL,
            email TEXT
        );

        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            teacher_id INTEGER,
            semester INTEGER NOT NULL,
            weekly_hours INTEGER NOT NULL DEFAULT 3,
            FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS subject_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL,
            semester INTEGER NOT NULL,
            section TEXT NOT NULL,
            teacher_id INTEGER NOT NULL,
            UNIQUE(subject_id, semester, section),
            FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
            FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semester INTEGER NOT NULL,
            section TEXT NOT NULL,
            room TEXT,
            UNIQUE(semester, section)
        );

        CREATE TABLE IF NOT EXISTS timetable (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id INTEGER NOT NULL,
            day TEXT NOT NULL,
            period TEXT NOT NULL,
            subject_id INTEGER,
            teacher_id INTEGER,
            room TEXT,
            entry_type TEXT NOT NULL DEFAULT 'regular',
            locked INTEGER NOT NULL DEFAULT 0,
            note TEXT,
            event_date TEXT,
            FOREIGN KEY (class_id) REFERENCES classes(id) ON DELETE CASCADE,
            FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE SET NULL,
            FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            audience TEXT NOT NULL,
            target TEXT,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS break_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            label TEXT NOT NULL
        );
    """)

    c.execute("SELECT COUNT(*) FROM break_settings")
    if c.fetchone()[0] == 0:
        c.executemany(
            "INSERT INTO break_settings (start_time, end_time, label) VALUES (?, ?, ?)",
            [
                (item["start"], item["end"], item["label"]) for item in BREAK_CONFIG
            ],
        )

    c.execute("SELECT COUNT(*) FROM admins")
    if c.fetchone()[0] == 0:
        c.execute(
            "INSERT INTO admins (email, password_hash) VALUES (?, ?)",
            ("admin@college.edu", hash_pw("admin123")),
        )

    # Preserve legacy single-teacher subjects by assigning them to every
    # existing class in their legacy semester.
    c.execute("""
        INSERT OR IGNORE INTO subject_assignments (subject_id, semester, section, teacher_id)
        SELECT s.id, s.semester, cls.section, s.teacher_id
        FROM subjects s
        JOIN classes cls ON cls.semester = s.semester
        WHERE s.teacher_id IS NOT NULL
    """)

    conn.commit()
    # Ensure legacy databases get the `locked` column
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(timetable)").fetchall()]
        if "locked" not in cols:
            conn.execute("ALTER TABLE timetable ADD COLUMN locked INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass
    conn.close()


def add_notification(audience: str, target: str | None, message: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO notifications (audience, target, message, created_at) VALUES (?, ?, ?, ?)",
        (audience, target, message, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()
    
def get_notifications(audience: str, target: str | None = None, limit: int = 20):
    conn = get_conn()
    if target:
        rows = conn.execute(
            "SELECT * FROM notifications WHERE audience IN ('all', ?) AND (target IS NULL OR target = ?) ORDER BY id DESC LIMIT ?",
            (audience, target, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM notifications WHERE audience IN ('all', ?) ORDER BY id DESC LIMIT ?",
            (audience, limit),
        ).fetchall()
    conn.close()
    return rows
