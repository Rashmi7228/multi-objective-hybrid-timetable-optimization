import sys
from pathlib import Path
# ensure project root is on sys.path so imports work when running from scripts/
sys.path.append(str(Path(__file__).resolve().parents[1]))

from generator import generate_timetable_for_class
from db import get_conn

def main():
    conn = get_conn()
    rows = conn.execute("SELECT id, semester, section FROM classes ORDER BY semester, section").fetchall()
    if not rows:
        print("No classes found")
        return
    for r in rows:
        cid = r['id']
        sem = r['semester']
        sec = r['section']
        print(f"Generating for class id={cid} (Sem {sem} Sec {sec})...")
        ok, msg = generate_timetable_for_class(cid)
        print(f"Result: {ok} - {msg}\n")

if __name__ == '__main__':
    main()
