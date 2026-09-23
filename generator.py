import random
from db import (
    get_conn,
    DAYS,
    PERIODS,
    add_notification,
    get_break_periods,
    find_teacher_conflict,
    find_class_conflict,
    find_room_conflict,
    TEACHER_UNAVAILABLE_MESSAGE,
    CLASS_UNAVAILABLE_MESSAGE,
    ROOM_UNAVAILABLE_MESSAGE,
)


def generate_timetable_for_class(class_id: int, clear_existing: bool = True) -> tuple[bool, str]:
    """Generate a weekly timetable for a class. Avoids teacher conflicts across all classes."""
    conn = get_conn()
    cls = conn.execute("SELECT * FROM classes WHERE id = ?", (class_id,)).fetchone()
    if not cls:
        conn.close()
        return False, "Class not found"

    subjects = conn.execute("""
        SELECT s.*, COALESCE(sa.teacher_id, s.teacher_id) AS assigned_teacher_id
        FROM subjects s
        LEFT JOIN subject_assignments sa
          ON sa.subject_id = s.id
         AND sa.semester = ?
         AND sa.section = ?
        WHERE sa.id IS NOT NULL OR (s.semester = ? AND s.teacher_id IS NOT NULL)
    """, (cls["semester"], cls["section"], cls["semester"])).fetchall()

    if not subjects:
        conn.close()
        return False, "No subjects with assigned teachers exist for this semester."

    if clear_existing:
        # Do not delete locked entries — preserve admin-locked timetable slots
        conn.execute(
            "DELETE FROM timetable WHERE class_id = ? AND entry_type IN ('regular','break') AND (locked IS NULL OR locked = 0)",
            (class_id,),
        )

    # Build remaining counts per subject (weekly hours to place)
    remaining = {s["id"]: s["weekly_hours"] for s in subjects}
    subj_map = {s["id"]: s for s in subjects}
    subject_ids = list(remaining.keys())
    random.shuffle(subject_ids)

    # Only count teaching periods (exclude break slots) when evaluating capacity
    break_periods = get_break_periods()
    teaching_periods = [p for p in PERIODS if p not in break_periods.keys()]
    total_slots = len(DAYS) * len(teaching_periods)
    # If total demand exceeds capacity, trim evenly from subjects
    total_demand = sum(remaining.values())
    if total_demand > total_slots:
        need_reduce = total_demand - total_slots
        # reduce one hour at a time from shuffled subject list
        idx = 0
        while need_reduce > 0:
            sid = subject_ids[idx % len(subject_ids)]
            if remaining[sid] > 0:
                remaining[sid] -= 1
                need_reduce -= 1
            idx += 1

    # Existing active commitments across all classes, including locked entries.
    busy = {}  # (day, period) -> set(teacher_ids)
    busy_rooms = {}  # (day, period) -> set(room names)
    rows = conn.execute(
        """
        SELECT day, period, teacher_id, room
        FROM timetable
        WHERE COALESCE(entry_type, 'regular') != 'cancelled'
        """
    ).fetchall()
    for r in rows:
        slot = (r["day"], r["period"])
        if r["teacher_id"] is not None:
            busy.setdefault(slot, set()).add(r["teacher_id"])
        if r["room"] and str(r["room"]).strip():
            busy_rooms.setdefault(slot, set()).add(r["room"])

    # Slots already used by this class, including extra/substitution entries.
    used_class_slots = set()
    rows = conn.execute(
        """
        SELECT day, period
        FROM timetable
        WHERE class_id = ?
          AND COALESCE(entry_type, 'regular') != 'cancelled'
        """,
        (class_id,),
    ).fetchall()
    for r in rows:
        used_class_slots.add((r["day"], r["period"]))

    # Free slots should exclude break periods so we never place subjects there
    # Free slots ordered by day then period (prefer filling earlier slots so free periods end up later)
    free_slots = [(d, p) for d in DAYS for p in teaching_periods if (d, p) not in used_class_slots]

    placed = 0
    unplaced = set()
    # Track per-day subject count to avoid same subject 3+ times same day
    day_subject_count = {(d, sid): 0 for d in DAYS for sid in [s["id"] for s in subjects]}
    # Track per-day teacher load to avoid overloading a teacher on one day
    teacher_day_count = {}

    # Place subjects trying to form consecutive blocks (prefer 3, then 2, then 1)
    progress = True
    while progress and any(v > 0 for v in remaining.values()):
        progress = False
        for sid in list(subject_ids):
            if remaining.get(sid, 0) <= 0:
                continue
            subj = subj_map[sid]
            teacher_id = subj["assigned_teacher_id"]
            # Subject hours are separate periods by default. Continuous blocks
            # are created only through the explicit manual duration control.
            placed_block = 0
            for block_size in (1,):
                if block_size > remaining[sid]:
                    continue
                found = None
                # Prefer days where this subject has not been scheduled yet,
                # then fill the earliest available period on that day.
                candidate_slots = sorted(
                    free_slots,
                    key=lambda slot: (
                        day_subject_count.get((slot[0], sid), 0),
                        DAYS.index(slot[0]),
                        PERIODS.index(slot[1]),
                    ),
                )
                for slot in candidate_slots:
                    d, p = slot
                    p_idx = PERIODS.index(p)
                    # ensure enough consecutive teaching periods ahead
                    block_periods = []
                    ok = True
                    for offset in range(block_size):
                        idx = p_idx + offset
                        if idx >= len(PERIODS):
                            ok = False
                            break
                        per = PERIODS[idx]
                        # skip if break period or not in teaching_periods
                        if per not in teaching_periods:
                            ok = False
                            break
                        # check slot not used
                        if (d, per) in used_class_slots:
                            ok = False
                            break
                        # teacher conflict
                        if teacher_id and teacher_id in busy.get((d, per), set()):
                            ok = False
                            break
                        if cls["room"] and str(cls["room"]).strip() and cls["room"] in busy_rooms.get((d, per), set()):
                            ok = False
                            break
                        # day subject limit: allow up to 3 periods of same subject per day
                        if day_subject_count.get((d, sid), 0) + block_size > 3:
                            ok = False
                            break
                        # teacher per-day balancing: avoid assigning more than 3 periods to a teacher in a day
                        if teacher_id:
                            tcount = teacher_day_count.get((d, teacher_id), 0)
                            if tcount + block_size > 3:
                                ok = False
                                break
                        block_periods.append(per)
                    if ok:
                        found = (d, block_periods)
                        break
                if found:
                    d, block_periods = found
                    for per in block_periods:
                        if find_teacher_conflict(conn, teacher_id, d, per):
                            conn.rollback()
                            conn.close()
                            return False, TEACHER_UNAVAILABLE_MESSAGE
                        if find_class_conflict(conn, class_id, d, per):
                            conn.rollback()
                            conn.close()
                            return False, CLASS_UNAVAILABLE_MESSAGE
                        if find_room_conflict(conn, cls["room"], d, per):
                            conn.rollback()
                            conn.close()
                            return False, ROOM_UNAVAILABLE_MESSAGE
                        conn.execute(
                            "INSERT INTO timetable (class_id, day, period, subject_id, teacher_id, room, entry_type) VALUES (?, ?, ?, ?, ?, ?, 'regular')",
                            (class_id, d, per, sid, teacher_id, cls["room"]),
                        )
                        busy.setdefault((d, per), set()).add(teacher_id)
                        if cls["room"] and str(cls["room"]).strip():
                            busy_rooms.setdefault((d, per), set()).add(cls["room"])
                        used_class_slots.add((d, per))
                        # remove from free_slots if present
                        try:
                            free_slots.remove((d, per))
                        except ValueError:
                            pass
                        day_subject_count[(d, sid)] = day_subject_count.get((d, sid), 0) + 1
                        if teacher_id:
                            teacher_day_count[(d, teacher_id)] = teacher_day_count.get((d, teacher_id), 0) + 1
                        placed += 1
                    remaining[sid] -= len(block_periods)
                    placed_block = len(block_periods)
                    progress = True
                    break
            if placed_block == 0:
                # couldn't place any block for this subject in this pass
                # mark as unplaced for reporting and skip further attempts
                unplaced.add(subj["name"])
                remaining[sid] = 0

    conn.commit()
    # Insert break entries (tea, lunch) for this class for each day
    conn = get_conn()
    for d in DAYS:
        for p in PERIODS:
            if p in break_periods.keys():
                # avoid duplicate if already exists
                exists = conn.execute(
                    "SELECT 1 FROM timetable WHERE class_id = ? AND day = ? AND period = ?",
                    (class_id, d, p),
                ).fetchone()
                if not exists:
                    conn.execute(
                        "INSERT INTO timetable (class_id, day, period, room, entry_type, note) VALUES (?, ?, ?, NULL, 'break', ?)",
                        (class_id, d, p, break_periods.get(p)),
                    )
    conn.commit()
    conn.close()

    target = f"{cls['semester']}-{cls['section']}"
    add_notification("student", target, f"Timetable generated for Sem {cls['semester']} Sec {cls['section']}.")
    add_notification("teacher", None, f"Timetable updated for Sem {cls['semester']} Sec {cls['section']}.")

    msg = f"Generated {placed} periods."
    if unplaced:
        msg += f" Could not place: {', '.join(unplaced)} (teacher, class, or room conflicts, or no free slot)."
    return True, msg
