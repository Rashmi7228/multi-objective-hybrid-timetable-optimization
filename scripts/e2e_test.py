import requests
from pprint import pprint

BASE = "http://127.0.0.1:5000"

def admin_session():
    s = requests.Session()
    r = s.post(f"{BASE}/api/admin/login", json={"email":"admin@college.edu","password":"admin123"})
    r.raise_for_status()
    return s

def teacher_session(name, passcode):
    s = requests.Session()
    r = s.post(f"{BASE}/api/teacher/login", json={"name":name,"passcode":passcode})
    r.raise_for_status()
    return s


def main():
    print("Starting end-to-end test against", BASE)
    s_admin = admin_session()
    print("Admin logged in")

    # create teachers
    def ensure_teacher(name, passcode, email):
        try:
            r = s_admin.post(f"{BASE}/api/admin/teachers", json={"name":name, "passcode":passcode, "email":email})
            if r.status_code not in (200,201):
                print(f"Create teacher response: {r.status_code} {r.text}")
        except Exception as e:
            print("Exception creating teacher:", e)

    ensure_teacher("Mr Kumar", "k123", "kumar@college.edu")
    ensure_teacher("Ms Priya", "p123", "priya@college.edu")

    r = s_admin.get(f"{BASE}/api/admin/teachers")
    r.raise_for_status()
    teachers = r.json()["items"]
    pprint(teachers)
    tk = next((t for t in teachers if t["name"]=="Mr Kumar"), None)
    sk = next((t for t in teachers if t["name"]=="Ms Priya"), None)
    if not tk or not sk:
        print("Teachers not found; aborting")
        return

    # create subject
    r = s_admin.post(f"{BASE}/api/admin/subjects", json={"code":"CS101","name":"Python","teacher_id":tk["id"],"semester":1,"weekly_hours":3})
    if r.status_code != 200:
        print("Subject create response:", r.status_code, r.text)

    # create class
    r = s_admin.post(f"{BASE}/api/admin/classes", json={"semester":1,"section":"A","room":"Room101"})
    if r.status_code != 200:
        print("Class create response:", r.status_code, r.text)

    r = s_admin.get(f"{BASE}/api/admin/classes")
    r.raise_for_status()
    classes = r.json()["items"]
    cls = next((c for c in classes if c["semester"]==1 and c["section"]=="A"), None)
    if not cls:
        print("Class not found; aborting")
        return
    print("Class id:", cls["id"])

    # generate timetable
    r = s_admin.post(f"{BASE}/api/admin/timetable/generate", json={"class_id": cls["id"]})
    print("Generate response:", r.status_code, r.text)

    # teacher apply leave
    s_teacher = teacher_session("Mr Kumar","k123")
    print("Teacher logged in")
    r = s_teacher.post(f"{BASE}/api/teacher/leave/apply", json={"start_date":"2026-08-17","end_date":"2026-08-17","leave_type":"Sick Leave","reason":"Not well"})
    print("Apply leave response:", r.status_code, r.text)

    # admin list pending leaves
    r = s_admin.get(f"{BASE}/api/admin/leaves?status=pending")
    r.raise_for_status()
    leaves = r.json()["items"]
    print("Pending leaves:")
    pprint(leaves)
    if not leaves:
        print("No pending leaves; aborting")
        return
    lid = leaves[0]["id"]

    # approve leave
    r = s_admin.post(f"{BASE}/api/admin/leaves/{lid}/decide", json={"action":"approve","note":"OK"})
    print("Approve response:", r.status_code, r.text)

    # fetch affected
    r = s_admin.get(f"{BASE}/api/admin/leaves/{lid}/affected")
    r.raise_for_status()
    af = r.json()
    print("Affected:")
    pprint(af)

    # assign substitute if any affected
    if af.get("items"):
        assigns = []
        for it in af["items"]:
            assigns.append({"class_id": it["class_id"], "day": it["day"], "period": it["period"], "substitute_teacher_id": sk["id"]})
        r = s_admin.post(f"{BASE}/api/admin/leaves/{lid}/assign", json={"assignments": assigns})
        print("Assign response:", r.status_code, r.text)
    else:
        print("No affected entries to assign")

    print("E2E test complete")

if __name__=="__main__":
    main()
