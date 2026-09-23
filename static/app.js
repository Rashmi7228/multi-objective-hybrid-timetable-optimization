// ===== College Timetable Frontend =====
const app = document.getElementById("app");
const navArea = document.getElementById("navArea");
const brand = document.getElementById("brand");
const toastEl = document.getElementById("toast");

let META = { days: [], periods: [], breaks: {}, breaks_meta: [] };
let SESSION = { role: null, user: null };
let lastSeenNotifId = parseInt(localStorage.getItem("lastSeenNotif") || "0");

function getBreakDefinition(period) {
  if (!Array.isArray(META.breaks_meta) || !META.periods.length) return null;
  const periodIndex = META.periods.indexOf(period);
  if (periodIndex === -1) return null;

  return META.breaks_meta.find((breakDef) => {
    const startIndex = META.periods.indexOf(breakDef.start);
    const endIndex = META.periods.indexOf(breakDef.end);
    const start = Math.min(startIndex, endIndex);
    const end = Math.max(startIndex, endIndex);
    return periodIndex >= start && periodIndex <= end;
  }) || null;
}

function isBreakPeriod(period) {
  return !!getBreakDefinition(period);
}

function breakCellText(period) {
  const breakDef = getBreakDefinition(period);
  if (!breakDef) return "BREAK";
  return (breakDef.label || "BREAK").toUpperCase();
}

function formatPeriodLabel(period) {
  const periodNumber = META.periods.indexOf(period) + 1;
  return periodNumber > 0 ? `Period ${periodNumber} — ${period}` : period;
}

function entryMergeKey(entry) {
  return [
    entry.subject_id ?? "",
    entry.teacher_id ?? "",
    entry.class_id ?? "",
    entry.room ?? "",
    entry.entry_type ?? "regular",
    entry.note ?? "",
    entry.locked ? "1" : "0",
  ].join("|");
}

function entriesSignature(entries) {
  return entries.map(entryMergeKey).sort().join("||");
}

function getEntryCellSpan(lookup, day, periodIndex) {
  const currentPeriod = META.periods[periodIndex];
  const currentItems = lookup[`${day}|${currentPeriod}`] || [];
  if (!currentItems.length || currentItems.some(item => item.entry_type === "break")) return 1;

  const signature = entriesSignature(currentItems);
  let span = 1;
  for (let nextIndex = periodIndex + 1; nextIndex < META.periods.length; nextIndex++) {
    const nextPeriod = META.periods[nextIndex];
    if (isBreakPeriod(nextPeriod)) break;
    const nextItems = lookup[`${day}|${nextPeriod}`] || [];
    if (!nextItems.length || entriesSignature(nextItems) !== signature) break;
    span += 1;
  }
  return span;
}

const api = async (path, opts = {}) => {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
};

const toast = (msg, kind = "") => {
  toastEl.textContent = msg;
  toastEl.className = "toast show " + kind;
  setTimeout(() => (toastEl.className = "toast"), 2600);
};

const el = (tag, attrs = {}, children = []) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k === "html") e.innerHTML = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2).toLowerCase(), v);
    else if (v !== null && v !== undefined) e.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (c == null) continue;
    e.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return e;
};

brand.onclick = () => navigate("home");

const navigate = (route, params = {}) => {
  location.hash = route + (Object.keys(params).length ? "?" + new URLSearchParams(params) : "");
};

const parseHash = () => {
  const h = location.hash.replace(/^#/, "") || "home";
  const [route, qs] = h.split("?");
  return { route, params: Object.fromEntries(new URLSearchParams(qs || "")) };
};

const renderNav = () => {
  navArea.innerHTML = "";
  if (SESSION.role) {
    navArea.appendChild(el("span", { class: "nav-pill" }, `${SESSION.role}: ${SESSION.user || ""}`));
    navArea.appendChild(el("button", {
      class: "btn secondary small",
      onclick: async () => { await api("/api/logout", { method: "POST" }); SESSION = { role: null, user: null }; navigate("home"); },
    }, "Logout"));
  }
};

window.addEventListener("hashchange", route);

async function init() {
  try {
    META = await api("/api/meta");
    const s = await api("/api/session");
    SESSION = s;
  } catch (e) {}
  renderNav();
  route();
}

function route() {
  const { route, params } = parseHash();
  renderNav();
  switch (route) {
    case "home": return renderHome();
    case "student": return renderStudent(params);
    case "teacher-login": return renderTeacherLogin();
    case "teacher": return renderTeacherPanel();
    case "admin-login": return renderAdminLogin();
    case "admin": return renderAdminPanel(params);
    default: return renderHome();
  }
}

// ============ HOME ============
function renderHome() {
  app.innerHTML = "";
  app.appendChild(el("h1", {}, "College Timetable System"));
  app.appendChild(el("p", { class: "subtitle" }, "Choose your panel to continue."));

  const grid = el("div", { class: "home-grid" });
  grid.appendChild(roleCard("AD", "Admin Panel",
    "Create and manage timetables, teachers, subjects, and classes. Full access.",
    () => navigate(SESSION.role === "admin" ? "admin" : "admin-login")));
  grid.appendChild(roleCard("TE", "Teacher Panel",
    "View your weekly or monthly timetable. Cancel, substitute, or schedule extra classes.",
    () => navigate(SESSION.role === "teacher" ? "teacher" : "teacher-login")));
  grid.appendChild(roleCard("ST", "Student Panel",
    "Enter your semester and section to view your class timetable. Read-only.",
    () => navigate("student")));
  app.appendChild(grid);
}

function roleCard(icon, title, desc, onClick) {
  return el("div", { class: "role-card", onclick: onClick }, [
    el("div", { class: "role-icon" }, icon),
    el("h3", {}, title),
    el("p", {}, desc),
  ]);
}

// ============ STUDENT ============
async function renderStudent(params) {
  app.innerHTML = "";
  app.appendChild(el("h1", {}, "Student Panel"));
  app.appendChild(el("p", { class: "subtitle" }, "Enter your semester and section to see your timetable."));

  const semInput = el("input", { type: "number", min: "1", max: "7", value: params.semester || "1" });
  const secInput = el("input", { type: "text", placeholder: "A", maxlength: "5", value: params.section || "" });
  const form = el("div", { class: "panel" }, [
    el("div", { class: "row" }, [
      el("div", { class: "field" }, [el("label", {}, "Semester"), semInput]),
      el("div", { class: "field" }, [el("label", {}, "Section"), secInput]),
      el("button", {
        class: "btn",
        onclick: () => {
          if (!secInput.value.trim()) return toast("Enter section", "error");
          navigate("student", { semester: semInput.value, section: secInput.value.trim().toUpperCase() });
        },
      }, "View Timetable"),
      el("button", {
        class: "btn secondary",
        onclick: () => {
          if (!secInput.value.trim()) return toast("Enter section", "error");
          navigate("student", { semester: semInput.value, section: secInput.value.trim().toUpperCase(), today: "1" });
        },
      }, "View Today's Timetable"),
    ]),
  ]);
  app.appendChild(form);

  if (params.semester && params.section) {
    try {
      const data = await api(`/api/student/timetable?semester=${params.semester}&section=${params.section}`);
      // If `today` param is present, render only today's timetable
      const dayName = new Date().toLocaleDateString(undefined, { weekday: "long" });
      const ttPanel = el("div", { class: "panel" }, [
        el("h2", {}, `Sem ${data.class.semester} · Section ${data.class.section}${data.class.room ? " · Room " + data.class.room : ""}`),
        params.today ? renderTimetableForDay(data.entries, dayName) : renderTimetableGrid(data.entries),
      ]);
      app.appendChild(ttPanel);

      const notif = await api(`/api/student/notifications?semester=${params.semester}&section=${params.section}`);
      app.appendChild(notifPanel("Notifications", notif.items));
    } catch (e) {
      app.appendChild(el("div", { class: "panel empty-state" }, e.message));
    }
  }
}

function renderTimetableGrid(entries) {
  const wrap = el("div", { class: "tt-wrap" });
  const table = el("table", { class: "tt" });
  const thead = el("thead");
  const headRow = el("tr", {}, [el("th", {}, "Day / Period"), ...META.periods.map(p => el("th", {}, p))]);
  thead.appendChild(headRow);
  table.appendChild(thead);

  const lookup = {};
  for (const e of entries) {
    const k = `${e.day}|${e.period}`;
    (lookup[k] = lookup[k] || []).push(e);
  }

  const tbody = el("tbody");
  for (const day of META.days) {
    const row = el("tr", {}, [el("th", {}, day)]);
    let periodIndex = 0;
    while (periodIndex < META.periods.length) {
      const period = META.periods[periodIndex];
      const breakDef = getBreakDefinition(period);
      if (breakDef) {
        const startIndex = META.periods.indexOf(breakDef.start);
        const endIndex = META.periods.indexOf(breakDef.end);
        const colspan = Math.max(1, Math.abs(endIndex - startIndex) + 1);
        const cell = el("td", { class: "cell break", colspan: String(colspan) });
        cell.appendChild(el("div", { class: "sub" }, breakCellText(period)));
        row.appendChild(cell);
        periodIndex += colspan;
        continue;
      }

      const items = lookup[`${day}|${period}`] || [];
      const span = getEntryCellSpan(lookup, day, periodIndex);
      const cell = el("td", span > 1 ? { colspan: String(span) } : {});
      if (!items.length) {
        cell.appendChild(el("div", { class: "cell empty" }, "—"));
      } else {
        const wrapper = el("div", { class: items.length > 1 ? "cell-multi" : "cell" });
        for (const it of items) {
          const c = el("div", { class: `cell ${it.entry_type}` });
          if (it.entry_type === "break") {
            c.appendChild(el("div", { class: "sub" }, it.note || breakCellText(it.period)));
          } else {
            const subText = it.subject_name || (it.entry_type === "cancelled" ? "Cancelled" : "—");
            c.appendChild(el("div", { class: "sub" }, subText));
            if (it.teacher_name) c.appendChild(el("div", { class: "tea" }, it.teacher_name));
            if (it.room) c.appendChild(el("div", { class: "room" }, it.room));
            if (it.entry_type !== "regular") {
              const badgeText = it.entry_type;
              c.appendChild(el("span", { class: "badge " + it.entry_type }, badgeText));
            }
          }
          wrapper.appendChild(c);
        }
        cell.appendChild(wrapper);
      }
      row.appendChild(cell);
      periodIndex += span;
    }
    tbody.appendChild(row);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
  return wrap;
}

function renderTimetableForDay(entries, dayName) {
  const wrap = el("div", { class: "tt-wrap" });
  const table = el("table", { class: "tt" });
  const thead = el("thead");
  thead.appendChild(el("tr", {}, [el("th", {}, "Day / Period"), ...META.periods.map(p => el("th", {}, p))]));
  table.appendChild(thead);

  const lookup = {};
  for (const e of entries) {
    const k = `${e.day}|${e.period}`;
    (lookup[k] = lookup[k] || []).push(e);
  }

  const tbody = el("tbody");
  const row = el("tr", {}, [el("th", {}, dayName)]);
  let periodIndex = 0;
  while (periodIndex < META.periods.length) {
    const period = META.periods[periodIndex];
    const breakDef = getBreakDefinition(period);
    if (breakDef) {
      const startIndex = META.periods.indexOf(breakDef.start);
      const endIndex = META.periods.indexOf(breakDef.end);
      const colspan = Math.max(1, Math.abs(endIndex - startIndex) + 1);
      const cell = el("td", { class: "cell break", colspan: String(colspan) });
      cell.appendChild(el("div", { class: "sub" }, breakCellText(period)));
      row.appendChild(cell);
      periodIndex += colspan;
      continue;
    }

    const items = lookup[`${dayName}|${period}`] || [];
    const span = getEntryCellSpan(lookup, dayName, periodIndex);
    const cell = el("td", span > 1 ? { colspan: String(span) } : {});
    if (!items.length) {
      cell.appendChild(el("div", { class: "cell empty" }, "—"));
    } else {
      const wrapper = el("div", { class: items.length > 1 ? "cell-multi" : "cell" });
      for (const it of items) {
        const c = el("div", { class: `cell ${it.entry_type}` });
        const breakLabel = it.note || (META.breaks && META.breaks[it.period]) || it.period;
        if (it.entry_type === "break") {
          c.appendChild(el("div", { class: "sub" }, breakLabel));
        } else {
          const subText = it.subject_name || (it.entry_type === "cancelled" ? "Cancelled" : "—");
          c.appendChild(el("div", { class: "sub" }, subText));
          if (it.teacher_name) c.appendChild(el("div", { class: "tea" }, it.teacher_name));
          if (it.room) c.appendChild(el("div", { class: "room" }, it.room));
          if (it.entry_type !== "regular") {
            const badgeText = it.entry_type;
            c.appendChild(el("span", { class: "badge " + it.entry_type }, badgeText));
          }
        }
        wrapper.appendChild(c);
      }
      cell.appendChild(wrapper);
    }
    row.appendChild(cell);
    periodIndex += span;
  }
  tbody.appendChild(row);
  table.appendChild(tbody);
  wrap.appendChild(table);
  return wrap;
}

function notifPanel(title, items) {
  const list = el("div", { class: "notif-list" });
  if (!items.length) {
    list.appendChild(el("div", { class: "empty-state" }, "No notifications yet."));
  } else {
    for (const n of items) {
      list.appendChild(el("div", { class: "notif" }, [
        el("div", {}, n.message),
        el("div", { class: "ts" }, new Date(n.created_at).toLocaleString()),
      ]));
    }
  }
  return el("div", { class: "panel" }, [el("h2", {}, title), list]);
}

// ============ TEACHER LOGIN ============
function renderTeacherLogin() {
  app.innerHTML = "";
  const wrap = el("div", { class: "auth-wrap" });
  const nameI = el("input", { type: "text", placeholder: "Your name (as registered)" });
  const passI = el("input", { type: "password", placeholder: "Passcode" });
  const submit = async () => {
    try {
      await api("/api/teacher/login", { method: "POST", body: { name: nameI.value, passcode: passI.value } });
      const s = await api("/api/session"); SESSION = s;
      toast("Welcome " + s.user, "success");
      navigate("teacher");
    } catch (e) { toast(e.message, "error"); }
  };
  passI.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
  wrap.appendChild(el("div", { class: "panel" }, [
    el("h2", {}, "Teacher Login"),
    el("div", { class: "field" }, [el("label", {}, "Name"), nameI]),
    el("div", { class: "field" }, [el("label", {}, "Passcode"), passI]),
    el("div", { class: "row", style: "margin-top:14px" }, [
      el("button", { class: "btn", onclick: submit }, "Login"),
      el("button", { class: "btn secondary", onclick: () => navigate("home") }, "Back"),
    ]),
  ]));
  app.appendChild(wrap);
}

// ============ TEACHER PANEL ============
async function renderTeacherPanel() {
  if (SESSION.role !== "teacher") return navigate("teacher-login");
  app.innerHTML = "";
  app.appendChild(el("h1", {}, `Welcome, ${SESSION.user}`));
  app.appendChild(el("p", { class: "subtitle" }, "Your weekly or monthly schedule."));

  const viewToggle = el("select", {}, [
    el("option", { value: "weekly" }, "Weekly View"),
    el("option", { value: "monthly" }, "Monthly View"),
  ]);
  const sortSel = el("select", {}, [
    el("option", { value: "day" }, "Sort: by Day"),
    el("option", { value: "subject" }, "Sort: by Subject"),
    el("option", { value: "class" }, "Sort: by Class"),
  ]);

  const controls = el("div", { class: "panel" }, [
    el("div", { class: "row" }, [
      el("div", { class: "field" }, [el("label", {}, "View"), viewToggle]),
      el("div", { class: "field" }, [el("label", {}, "Sort"), sortSel]),
      el("div", { class: "spacer" }),
      el("button", { class: "btn warn", onclick: () => openExtraClassModal() }, "+ Extra Class"),
    ]),
  ]);
  app.appendChild(controls);

  const ttHolder = el("div");
  app.appendChild(ttHolder);

  const refresh = async () => {
    const data = await api("/api/teacher/timetable");
    ttHolder.innerHTML = "";
    if (viewToggle.value === "weekly") {
      ttHolder.appendChild(el("div", { class: "panel" }, [
        el("h2", {}, "Weekly Timetable"),
        renderTeacherWeekly(data.entries),
      ]));
    } else {
      ttHolder.appendChild(el("div", { class: "panel" }, [
        el("h2", {}, "Monthly View (List)"),
        renderTeacherList(sortEntries(data.entries, sortSel.value), refresh),
      ]));
    }
  };
  viewToggle.onchange = refresh;
  sortSel.onchange = refresh;
  await refresh();

  const notif = await api("/api/teacher/notifications");
  app.appendChild(notifPanel("Notifications", notif.items));
    // Leave management section
    app.appendChild(el("div", { class: "panel" }, [el("h2", {}, "Leave Management"), renderTeacherLeaves()]));
}

  function renderTeacherLeaves() {
    const wrap = el("div");
    const startI = el("input", { type: "date" });
    const endI = el("input", { type: "date" });
    const typeSel = el("select", {}, ["Casual Leave", "Sick Leave", "Emergency Leave"].map(v => el("option", { value: v }, v)));
    const reasonI = el("input", { type: "text", placeholder: "Reason (optional)" });
    const listHolder = el("div");

    async function submit() {
      try {
        await api("/api/teacher/leave/apply", { method: "POST", body: { start_date: startI.value, end_date: endI.value || startI.value, leave_type: typeSel.value, reason: reasonI.value } });
        toast("Leave submitted", "success");
        startI.value = ""; endI.value = ""; reasonI.value = "";
        await refreshList();
      } catch (e) { toast(e.message, "error"); }
    }

    async function refreshList() {
      try {
        const res = await api("/api/teacher/leave/list");
        listHolder.innerHTML = "";
        if (!res.items.length) listHolder.appendChild(el("div", { class: "empty-state" }, "No leave requests yet."));
        else for (const l of res.items) {
          listHolder.appendChild(el("div", { class: "notif" }, [
            el("div", {}, `${l.leave_type} · ${l.start_date}${l.end_date && l.end_date !== l.start_date ? ' - ' + l.end_date : ''}`),
            el("div", { class: "muted" }, `${l.status.toUpperCase()} ${l.admin_note ? '· Admin: ' + l.admin_note : ''}`),
          ]));
        }
      } catch (e) { listHolder.innerHTML = el("div", { class: "empty-state" }, e.message); }
    }

    wrap.appendChild(el("div", { class: "row" }, [
      el("div", { class: "field" }, [el("label", {}, "Start Date"), startI]),
      el("div", { class: "field" }, [el("label", {}, "End Date (optional)"), endI]),
      el("div", { class: "field" }, [el("label", {}, "Type"), typeSel]),
    ]));
    wrap.appendChild(el("div", { class: "row" }, [el("div", { class: "field" }, [el("label", {}, "Reason"), reasonI]), el("button", { class: "btn", onclick: submit }, "Apply") ]));
    wrap.appendChild(el("div", { style: "margin-top:12px" }, [el("h3", {}, "Your Requests"), listHolder]));
    refreshList();
    return wrap;
  }
function sortEntries(entries, by) {
  const dayOrder = Object.fromEntries(META.days.map((d, i) => [d, i]));
  const arr = [...entries];
  if (by === "day") arr.sort((a, b) => (dayOrder[a.day] - dayOrder[b.day]) || a.period.localeCompare(b.period));
  if (by === "subject") arr.sort((a, b) => (a.subject_name || "").localeCompare(b.subject_name || ""));
  if (by === "class") arr.sort((a, b) => (a.semester - b.semester) || (a.section || "").localeCompare(b.section || ""));
  return arr;
}

function renderTeacherWeekly(entries) {
  const wrap = el("div", { class: "tt-wrap" });
  const table = el("table", { class: "tt" });
  const thead = el("thead");
  thead.appendChild(el("tr", {}, [el("th", {}, "Day / Period"), ...META.periods.map(p => el("th", {}, p))]));
  table.appendChild(thead);

  const lookup = {};
  for (const e of entries) (lookup[`${e.day}|${e.period}`] = lookup[`${e.day}|${e.period}`] || []).push(e);

  const tbody = el("tbody");
  for (const day of META.days) {
    const row = el("tr", {}, [el("th", {}, day)]);
    let periodIndex = 0;
    while (periodIndex < META.periods.length) {
      const period = META.periods[periodIndex];
      const breakDef = getBreakDefinition(period);
      if (breakDef) {
        const startIndex = META.periods.indexOf(breakDef.start);
        const endIndex = META.periods.indexOf(breakDef.end);
        const colspan = Math.max(1, Math.abs(endIndex - startIndex) + 1);
        const td = el("td", { class: "cell break", colspan: String(colspan) });
        td.appendChild(el("div", { class: "sub" }, breakCellText(period)));
        td.style.cursor = "pointer";
        row.appendChild(td);
        periodIndex += colspan;
        continue;
      }

      const items = lookup[`${day}|${period}`] || [];
      const span = getEntryCellSpan(lookup, day, periodIndex);
      const td = el("td", span > 1 ? { colspan: String(span) } : {});
      if (!items.length) td.appendChild(el("div", { class: "cell empty" }, "—"));
      else {
        const wrapper = el("div", { class: items.length > 1 ? "cell-multi" : "cell" });
        for (const it of items) {
          const c = el("div", { class: `cell ${it.entry_type}` });
        if (it.entry_type === "break") {
          c.appendChild(el("div", { class: "sub" }, it.note || (META.breaks && META.breaks[it.period]) || "BREAK"));
        } else {
          c.appendChild(el("div", { class: "sub" }, it.subject_name || "—"));
          c.appendChild(el("div", { class: "tea" }, `Sem ${it.semester} · ${it.section}`));
          if (it.entry_type !== "regular") {
            const badgeText = it.entry_type;
            c.appendChild(el("span", { class: "badge " + it.entry_type }, badgeText));
          }
        }
        c.style.cursor = "pointer";
          c.onclick = () => openTeacherActionModal(it);
          wrapper.appendChild(c);
        }
        td.appendChild(wrapper);
      }
      row.appendChild(td);
      periodIndex += span;
    }
    tbody.appendChild(row);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
  return wrap;
}

function renderTeacherList(entries, refresh) {
  const tbl = el("table");
  tbl.appendChild(el("thead", {}, el("tr", {}, [
    el("th", {}, "Day"), el("th", {}, "Period"), el("th", {}, "Subject"),
    el("th", {}, "Class"), el("th", {}, "Type"), el("th", {}, "Actions"),
  ])));
  const tb = el("tbody");
  for (const e of entries) {
    tb.appendChild(el("tr", {}, [
      el("td", {}, e.day),
      el("td", {}, e.period),
      el("td", {}, e.subject_name || "—"),
      el("td", {}, `Sem ${e.semester} · ${e.section}`),
      el("td", {}, [
        el("span", { class: "badge " + e.entry_type }, e.entry_type),
        e.locked ? el("span", { class: "badge lock" }, "Locked") : null,
      ]),
      el("td", {}, [
        el("button", { class: "btn small secondary", onclick: () => openTeacherActionModal(e, refresh) }, "Manage"),
      ]),
    ]));
  }
  tbl.appendChild(tb);
  if (!entries.length) return el("div", { class: "empty-state" }, "No classes scheduled.");
  return tbl;
}

async function openTeacherActionModal(entry, refresh) {
  const colleagues = (await api("/api/teacher/colleagues")).items;
  const noteI = el("input", { type: "text", placeholder: "Optional note" });
  const subSel = el("select", {}, [
    el("option", { value: "" }, "Select substitute teacher..."),
    ...colleagues.map(c => el("option", { value: c.id }, c.name)),
  ]);

  const close = openModal("Manage Class", [
    el("p", { class: "muted" }, `${entry.day} · ${entry.period} · ${entry.subject_name || ""}`),
    el("div", { class: "field" }, [el("label", {}, "Note"), noteI]),
    el("div", { class: "field" }, [el("label", {}, "Substitute Teacher"), subSel]),
    el("div", { class: "row", style: "margin-top:14px;justify-content:flex-end" }, [
      el("button", { class: "btn danger", onclick: async () => {
        await api("/api/teacher/action", { method: "POST", body: { action: "cancel", entry_id: entry.id, note: noteI.value } });
        toast("Class cancelled", "success"); close(); route();
      } }, "Cancel Class"),
      el("button", { class: "btn warn", onclick: async () => {
        if (!subSel.value) return toast("Pick a substitute teacher", "error");
        await api("/api/teacher/action", { method: "POST", body: { action: "substitute", entry_id: entry.id, substitute_teacher_id: parseInt(subSel.value), note: noteI.value } });
        toast("Substitution recorded", "success"); close(); route();
      } }, "Substitute"),
      el("button", { class: "btn secondary", onclick: () => close() }, "Close"),
    ]),
  ]);
}

async function openExtraClassModal() {
  const own = (await api("/api/teacher/own-classes")).items;
  const classes = own.length ? own : (await api("/api/classes")).items;
  const classSel = el("select", {}, classes.map(c => el("option", { value: c.id }, `Sem ${c.semester} · ${c.section}`)));
  const daySel = el("select", {}, META.days.map(d => el("option", { value: d }, d)));
  const periodSel = el("select", {}, META.periods.map(p => el("option", { value: p }, formatPeriodLabel(p))));
  const dateI = el("input", { type: "date" });
  const noteI = el("input", { type: "text", placeholder: "What's this extra class about?" });

  const close = openModal("Schedule Extra Class", [
    el("div", { class: "field" }, [el("label", {}, "Class"), classSel]),
    el("div", { class: "row" }, [
      el("div", { class: "field" }, [el("label", {}, "Day"), daySel]),
      el("div", { class: "field" }, [el("label", {}, "Period"), periodSel]),
    ]),
    el("div", { class: "field" }, [el("label", {}, "Date (optional)"), dateI]),
    el("div", { class: "field" }, [el("label", {}, "Note"), noteI]),
    el("div", { class: "row", style: "margin-top:14px;justify-content:flex-end" }, [
      el("button", { class: "btn", onclick: async () => {
        await api("/api/teacher/action", { method: "POST", body: {
          action: "extra", class_id: parseInt(classSel.value),
          day: daySel.value, period: periodSel.value,
          event_date: dateI.value || null, note: noteI.value,
        }});
        toast("Extra class added", "success"); close(); route();
      } }, "Add"),
      el("button", { class: "btn secondary", onclick: () => close() }, "Cancel"),
    ]),
  ]);
}

// ============ ADMIN LOGIN ============
function renderAdminLogin() {
  app.innerHTML = "";
  const wrap = el("div", { class: "auth-wrap" });
  const emailI = el("input", { type: "email", placeholder: "Enter Email" });
  const passI = el("input", { type: "password", placeholder: "Enter Password" });
  const submit = async () => {
    try {
      await api("/api/admin/login", { method: "POST", body: { email: emailI.value, password: passI.value } });
      const s = await api("/api/session"); SESSION = s;
      toast("Welcome", "success"); navigate("admin");
    } catch (e) { toast(e.message, "error"); }
  };
  passI.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
  wrap.appendChild(el("div", { class: "panel" }, [
    el("h2", {}, "Admin Login"),
    el("div", { class: "field" }, [el("label", {}, "Email"), emailI]),
    el("div", { class: "field" }, [el("label", {}, "Password"), passI]),
    el("div", { class: "row", style: "margin-top:14px" }, [
      el("button", { class: "btn", onclick: submit }, "Login"),
      el("button", { class: "btn secondary", onclick: () => navigate("home") }, "Back"),
    ]),
  ]));
  app.appendChild(wrap);
}

// ============ ADMIN PANEL ============
async function renderAdminPanel(params) {
  if (SESSION.role !== "admin") return navigate("admin-login");
  app.innerHTML = "";
  app.appendChild(el("h1", {}, "Admin Panel"));
  app.appendChild(el("p", { class: "subtitle" }, "Manage everything: teachers, subjects, classes, and timetables."));

  const tabs = ["Timetables", "Classes", "Subjects", "Teachers"];
  // include Leaves management
  tabs.push("Leaves");
  const active = params.tab || "Timetables";
  const tabBar = el("div", { class: "tabs" });
  tabs.forEach(t => tabBar.appendChild(el("div", {
    class: "tab" + (t === active ? " active" : ""),
    onclick: () => navigate("admin", { tab: t }),
  }, t)));
  app.appendChild(tabBar);

  const content = el("div");
  app.appendChild(content);
  if (active === "Teachers") await adminTeachers(content);
  else if (active === "Subjects") await adminSubjects(content);
  else if (active === "Classes") await adminClasses(content);
  else if (active === "Leaves") await adminLeaves(content);
  else await adminTimetables(content);
}

function compareSortValues(left, right, direction = "asc") {
  const leftNumber = Number(left);
  const rightNumber = Number(right);
  let result;
  if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber) && left !== "" && right !== "") {
    result = leftNumber - rightNumber;
  } else {
    result = String(left ?? "").localeCompare(String(right ?? ""), undefined, { numeric: true, sensitivity: "base" });
  }
  return direction === "desc" ? -result : result;
}

function sortControl(label, options, onChange) {
  const sortSel = el("select", {}, options.map(option => el("option", { value: option.value }, option.label)));
  const directionSel = el("select", {}, [
    el("option", { value: "asc" }, "A → Z / Low → High"),
    el("option", { value: "desc" }, "Z → A / High → Low"),
  ]);
  const update = () => onChange(sortSel.value, directionSel.value);
  sortSel.addEventListener("change", update);
  directionSel.addEventListener("change", update);
  return el("div", { class: "row sort-controls" }, [
    el("div", { class: "field" }, [el("label", {}, label), sortSel]),
    el("div", { class: "field" }, [el("label", {}, "Order"), directionSel]),
  ]);
}

async function adminTeachers(content) {
  const data = await api("/api/admin/teachers");
  const nameI = el("input", { type: "text", placeholder: "Full name" });
  const emailI = el("input", { type: "email", placeholder: "email@college.edu" });
  const passI = el("input", { type: "text", placeholder: "Passcode" });
  content.appendChild(el("div", { class: "panel" }, [
    el("h2", {}, "Add Teacher"),
    el("div", { class: "row" }, [
      el("div", { class: "field" }, [el("label", {}, "Name"), nameI]),
      el("div", { class: "field" }, [el("label", {}, "Email"), emailI]),
      el("div", { class: "field" }, [el("label", {}, "Passcode"), passI]),
      el("button", { class: "btn", onclick: async () => {
        try {
          await api("/api/admin/teachers", { method: "POST", body: {
            name: nameI.value, email: emailI.value, passcode: passI.value,
          } });
          toast("Teacher added", "success"); route();
        } catch (e) { toast(e.message, "error"); }
      } }, "Add"),
    ]),
  ]));

  const tableHolder = el("div");
  const renderTable = (sortBy = "name", direction = "asc") => {
    tableHolder.innerHTML = "";
    if (!data.items.length) {
      tableHolder.appendChild(el("div", { class: "empty-state" }, "No teachers yet."));
      return;
    }
    const items = [...data.items].sort((left, right) => compareSortValues(left[sortBy], right[sortBy], direction));
    const tbl = el("table");
    tbl.appendChild(el("thead", {}, el("tr", {}, [
      el("th", {}, "Name"), el("th", {}, "Email"), el("th", {}, ""),
    ])));
    const tb = el("tbody");
    for (const t of items) {
      tb.appendChild(el("tr", {}, [
        el("td", {}, t.name),
        el("td", {}, t.email || "—"),
        el("td", { class: "right" }, [
          el("button", { class: "btn small secondary", onclick: () => editTeacherModal(t) }, "Edit"),
          el("button", { class: "btn small danger", style: "margin-left:6px", onclick: async () => {
            if (!confirm(`Delete ${t.name}?`)) return;
            try {
              await api(`/api/admin/teachers/${t.id}`, { method: "DELETE" });
              toast("Teacher deleted", "success");
              route();
            } catch (e) { toast(e.message, "error"); }
          } }, "Delete"),
        ]),
      ]));
    }
    tbl.appendChild(tb);
    tableHolder.appendChild(tbl);
  };
  const controls = sortControl("Sort By", [
    { value: "name", label: "Teacher Name" },
    { value: "id", label: "ID" },
  ], renderTable);
  renderTable();
  content.appendChild(el("div", { class: "panel" }, [el("h2", {}, "Teachers"), controls, tableHolder]));
}

function editTeacherModal(t) {
  const nameI = el("input", { type: "text", value: t.name });
  const emailI = el("input", { type: "email", value: t.email || "" });
  const passI = el("input", { type: "text", placeholder: "Leave blank to keep" });
  const close = openModal("Edit Teacher", [
    el("div", { class: "field" }, [el("label", {}, "Name"), nameI]),
    el("div", { class: "field" }, [el("label", {}, "Email"), emailI]),
    el("div", { class: "field" }, [el("label", {}, "New Passcode"), passI]),
    el("div", { class: "row", style: "margin-top:14px;justify-content:flex-end" }, [
      el("button", { class: "btn", onclick: async () => {
        await api(`/api/admin/teachers/${t.id}`, { method: "PUT", body: {
          name: nameI.value, email: emailI.value, passcode: passI.value,
        }});
        toast("Updated", "success"); close(); route();
      } }, "Save"),
      el("button", { class: "btn secondary", onclick: () => close() }, "Cancel"),
    ]),
  ]);
}

async function adminSubjects(content) {
  const [subs, teachers] = await Promise.all([api("/api/admin/subjects"), api("/api/admin/teachers")]);
  let editingSubject = null;
  const assignmentRows = [];
  const codeI = el("input", { type: "text", placeholder: "CS101" });
  const nameI = el("input", { type: "text", placeholder: "Computer Science" });
  const hoursI = el("input", { type: "number", min: "1", max: "10", value: "3" });
  const assignmentsWrap = el("div", { class: "subject-assignments" });
  function addAssignmentRow(assignment = {}) {
    const semesterI = el("input", { type: "number", min: "1", max: "20", value: assignment.semester || "1" });
    const sectionI = el("input", { type: "text", placeholder: "A", value: assignment.section || "", maxlength: "5" });
    const teaSel = el("select", {}, [
      el("option", { value: "" }, "— Select teacher —"),
      ...teachers.items.map(t => el("option", { value: t.id, selected: assignment.teacher_id === t.id ? "selected" : null }, t.name)),
    ]);
    const row = el("div", { class: "row subject-assignment" }, [
      el("div", { class: "field" }, [el("label", {}, "Semester"), semesterI]),
      el("div", { class: "field" }, [el("label", {}, "Section"), sectionI]),
      el("div", { class: "field" }, [el("label", {}, "Teacher"), teaSel]),
      el("button", { class: "btn small danger", type: "button", onclick: () => {
        const index = assignmentRows.findIndex(item => item.row === row);
        if (index >= 0) assignmentRows.splice(index, 1);
        row.remove();
      }}, "Delete Assignment"),
    ]);
    assignmentRows.push({ row, semesterI, sectionI, teaSel });
    assignmentsWrap.appendChild(row);
  }
  const addAssignmentButton = el("button", { class: "btn small secondary", type: "button", onclick: () => addAssignmentRow() }, "Add Assignment");
  content.appendChild(el("div", { class: "panel" }, [
    el("h2", { id: "subject-form-title" }, "Add Subject"),
    el("div", { class: "row" }, [
      el("div", { class: "field" }, [el("label", {}, "Code"), codeI]),
      el("div", { class: "field" }, [el("label", {}, "Name"), nameI]),
      el("div", { class: "field" }, [el("label", {}, "Weekly Hours"), hoursI]),
      el("button", { id: "subject-form-submit", class: "btn", onclick: async () => {
        try {
          const endpoint = editingSubject ? `/api/admin/subjects/${editingSubject.id}` : "/api/admin/subjects";
          const assignments = assignmentRows.map(({ semesterI, sectionI, teaSel }) => ({
            semester: semesterI.value, section: sectionI.value, teacher_id: teaSel.value,
          }));
          await api(endpoint, { method: editingSubject ? "PUT" : "POST", body: {
            code: codeI.value, name: nameI.value, weekly_hours: hoursI.value, assignments,
          }});
          toast(editingSubject ? "Subject updated" : "Subject added", "success"); route();
        } catch (e) { toast(e.message, "error"); }
      }}, "Add Subject"),
    ]),
    el("div", { class: "row", style: "margin-top:14px;justify-content:space-between" }, [
      el("h3", { style: "margin:0" }, "Assignments"), addAssignmentButton,
    ]),
    assignmentsWrap,
  ]));

  const tableHolder = el("div");
  const renderTable = (sortBy = "code", direction = "asc") => {
    tableHolder.innerHTML = "";
    if (!subs.items.length) {
      tableHolder.appendChild(el("div", { class: "empty-state" }, "No subjects yet."));
      return;
    }
    const items = [...subs.items].sort((left, right) => compareSortValues(left[sortBy], right[sortBy], direction));
    const tbl = el("table");
    tbl.appendChild(el("thead", {}, el("tr", {}, [
      el("th", {}, "Code"), el("th", {}, "Name"), el("th", {}, "Sem"),
      el("th", {}, "Hours/Wk"), el("th", {}, "Teacher"), el("th", {}, ""),
    ])));
    const tb = el("tbody");
    for (const s of items) {
      tb.appendChild(el("tr", {}, [
        el("td", {}, s.code), el("td", {}, s.name), el("td", {}, String(s.semester)),
        el("td", {}, String(s.weekly_hours)), el("td", {}, s.teacher_name || "—"),
        el("td", { class: "right" }, [
          el("button", { class: "btn small secondary", onclick: () => {
            editingSubject = s;
            codeI.value = s.code;
            nameI.value = s.name;
            hoursI.value = s.weekly_hours;
            assignmentRows.splice(0).forEach(() => {});
            assignmentsWrap.innerHTML = "";
            (s.assignments || []).forEach(addAssignmentRow);
            content.querySelector("#subject-form-title").textContent = "Edit Subject";
            content.querySelector("#subject-form-submit").textContent = "Update Subject";
            codeI.focus();
          }}, "Edit"),
          el("button", { class: "btn small danger", onclick: async () => {
            if (!confirm(`Delete ${s.name}?`)) return;
            try {
              await api(`/api/admin/subjects/${s.id}`, { method: "DELETE" });
              toast("Subject deleted", "success");
              route();
            } catch (e) { toast(e.message, "error"); }
          }}, "Delete"),
        ]),
      ]));
    }
    tbl.appendChild(tb);
    tableHolder.appendChild(tbl);
  };
  const controls = sortControl("Sort By", [
    { value: "code", label: "Subject Code" },
    { value: "name", label: "Subject Name" },
    { value: "semester", label: "Semester" },
    { value: "weekly_hours", label: "Hours" },
  ], renderTable);
  renderTable("semester");
  content.appendChild(el("div", { class: "panel" }, [el("h2", {}, "Subjects"), controls, tableHolder]));
}

async function adminClasses(content) {
  const data = await api("/api/admin/classes");
  const semI = el("input", { type: "number", min: "1", max: "7", value: "1" });
  const secI = el("input", { type: "text", placeholder: "A", maxlength: "5" });
  const roomI = el("input", { type: "text", placeholder: "Room 101" });
  content.appendChild(el("div", { class: "panel" }, [
    el("h2", {}, "Add Class"),
    el("div", { class: "row" }, [
      el("div", { class: "field" }, [el("label", {}, "Semester"), semI]),
      el("div", { class: "field" }, [el("label", {}, "Section"), secI]),
      el("div", { class: "field" }, [el("label", {}, "Room"), roomI]),
      el("button", { class: "btn", onclick: async () => {
        try {
          await api("/api/admin/classes", { method: "POST", body: {
            semester: semI.value, section: secI.value, room: roomI.value,
          }});
          toast("Class added", "success"); route();
        } catch (e) { toast(e.message, "error"); }
      }}, "Add"),
    ]),
  ]));

  const tableHolder = el("div");
  const renderTable = (sortBy = "semester", direction = "asc") => {
    tableHolder.innerHTML = "";
    if (!data.items.length) {
      tableHolder.appendChild(el("div", { class: "empty-state" }, "No classes yet."));
      return;
    }
    const items = [...data.items].sort((left, right) => {
      if (sortBy === "class_name") {
        const semesterResult = compareSortValues(left.semester, right.semester, direction);
        return semesterResult || compareSortValues(left.section, right.section, direction);
      }
      return compareSortValues(left[sortBy], right[sortBy], direction);
    });
    const tbl = el("table");
    tbl.appendChild(el("thead", {}, el("tr", {}, [
      el("th", {}, "Semester"), el("th", {}, "Section"), el("th", {}, "Room"), el("th", {}, ""),
    ])));
    const tb = el("tbody");
    for (const c of items) {
      tb.appendChild(el("tr", {}, [
        el("td", {}, String(c.semester)), el("td", {}, c.section), el("td", {}, c.room || "—"),
        el("td", { class: "right" }, [
          el("button", { class: "btn small secondary", onclick: () => editClassModal(c) }, "Edit"),
          el("button", { class: "btn small danger", onclick: async () => {
            if (!confirm(`Delete Sem ${c.semester} · ${c.section}? This removes its timetable.`)) return;
            try {
              await api(`/api/admin/classes/${c.id}`, { method: "DELETE" });
              toast("Class deleted", "success");
              route();
            } catch (e) { toast(e.message, "error"); }
          }}, "Delete"),
        ]),
      ]));
    }
    tbl.appendChild(tb);
    tableHolder.appendChild(tbl);
  };
  const controls = sortControl("Sort By", [
    { value: "semester", label: "Semester" },
    { value: "section", label: "Section" },
    { value: "class_name", label: "Class Name" },
  ], renderTable);
  renderTable();
  content.appendChild(el("div", { class: "panel" }, [el("h2", {}, "Classes"), controls, tableHolder]));
}

function editClassModal(classItem) {
  const semesterI = el("input", { type: "number", min: "1", max: "7", value: classItem.semester });
  const sectionI = el("input", { type: "text", maxlength: "5", value: classItem.section });
  const roomI = el("input", { type: "text", value: classItem.room || "" });
  const close = openModal("Edit Class", [
    el("div", { class: "field" }, [el("label", {}, "Semester"), semesterI]),
    el("div", { class: "field" }, [el("label", {}, "Section"), sectionI]),
    el("div", { class: "field" }, [el("label", {}, "Room"), roomI]),
    el("div", { class: "row", style: "margin-top:14px;justify-content:flex-end" }, [
      el("button", { class: "btn", onclick: async () => {
        try {
          await api(`/api/admin/classes/${classItem.id}`, { method: "PUT", body: {
            semester: semesterI.value, section: sectionI.value, room: roomI.value,
          }});
          toast("Class updated", "success");
          close();
          route();
        } catch (e) { toast(e.message, "error"); }
      } }, "Save"),
      el("button", { class: "btn secondary", onclick: () => close() }, "Cancel"),
    ]),
  ]);
}

async function adminTimetables(content) {
  const classes = (await api("/api/admin/classes")).items;
  if (!classes.length) {
    content.appendChild(el("div", { class: "panel empty-state" }, "Create a class first under the Classes tab."));
    return;
  }
  const classSel = el("select", {}, classes.map(c => el("option", { value: c.id }, `Sem ${c.semester} · Section ${c.section}`)));

  const ctrlPanel = el("div", { class: "panel" }, [
    el("div", { class: "row" }, [
      el("div", { class: "field" }, [el("label", {}, "Class"), classSel]),
      el("button", { class: "btn", onclick: async () => {
        if (!confirm("Auto-generate timetable for this class? Existing regular entries will be replaced.")) return;
        try {
          const res = await api("/api/admin/timetable/generate", { method: "POST", body: { class_id: parseInt(classSel.value) } });
          toast(res.message, "success"); refresh();
        } catch (e) { toast(e.message, "error"); }
      } }, "Auto-Generate"),
      el("button", { class: "btn secondary", onclick: () => openAdminEntryModal(parseInt(classSel.value), null, refresh) }, "+ Add Entry"),
    ]),
  ]);
  content.appendChild(ctrlPanel);

  const ttHolder = el("div");
  content.appendChild(ttHolder);

  const refresh = async () => {
    const data = await api(`/api/admin/timetable?class_id=${classSel.value}`);
    ttHolder.innerHTML = "";
    ttHolder.appendChild(el("div", { class: "panel" }, [
      el("h2", {}, `Timetable · Sem ${data.class.semester} · Section ${data.class.section}`),
      renderAdminTimetable(data.entries, parseInt(classSel.value), refresh),
    ]));
  };
  classSel.onchange = refresh;
  await refresh();
}

async function adminLeaves(content) {
  const panel = el("div");
  const filterSel = el("select", {}, [el("option", { value: "" }, "All"), el("option", { value: "pending" }, "Pending"), el("option", { value: "approved" }, "Approved"), el("option", { value: "rejected" }, "Rejected")]);
  const searchI = el("input", { type: "text", placeholder: "Search teacher name" });
  const listHolder = el("div");

  async function refresh() {
    const status = filterSel.value;
    const q = searchI.value.trim();
    const res = await api(`/api/admin/leaves?status=${encodeURIComponent(status)}&q=${encodeURIComponent(q)}`);
    listHolder.innerHTML = "";
    if (!res.items.length) listHolder.appendChild(el("div", { class: "empty-state" }, "No leave requests."));
    else for (const l of res.items) {
      const row = el("div", { class: "panel" }, [
        el("div", { class: "row" }, [
          el("div", { class: "field" }, [
            el("strong", {}, l.teacher_name),
            el("div", { class: "muted" }, `${l.leave_type} · ${l.start_date}${l.end_date && l.end_date !== l.start_date ? ' - ' + l.end_date : ''}`),
          ]),
          el("div", { class: "spacer" }),
          el("div", {}, [
            el("button", { class: "btn", onclick: async () => {
              try {
                await api(`/api/admin/leaves/${l.id}/decide`, { method: "POST", body: { action: "approve" } });
                toast("Approved", "success");
                refresh();
              } catch (e) {
                toast(e.message || "Approval failed", "error");
              }
            } }, "Approve"),
            el("button", { class: "btn danger", style: "margin-left:8px", onclick: async () => {
              const reasonInput = el("input", { type: "text", placeholder: "Reason (optional)" });
              const close = openModal("Reject Leave", [
                el("div", { class: "field" }, [
                  el("label", {}, "Reason"),
                  reasonInput,
                ]),
                el("div", { class: "row", style: "margin-top:12px;justify-content:flex-end" }, [
                  el("button", { class: "btn danger", onclick: async () => {
                    try {
                      await api(`/api/admin/leaves/${l.id}/decide`, { method: "POST", body: { action: "reject", note: reasonInput.value || "" } });
                      toast("Rejected", "success");
                      close();
                      refresh();
                    } catch (e) {
                      toast(e.message || "Rejection failed", "error");
                    }
                  } }, "Reject"),
                  el("button", { class: "btn secondary", onclick: () => close() }, "Cancel"),
                ]),
              ]);
            } }, "Reject"),
            el("button", { class: "btn secondary", style: "margin-left:8px", onclick: async () => {
              const af = await api(`/api/admin/leaves/${l.id}/affected`);
              if (!af.items.length) return alert("No affected timetable entries found for this leave.");
              const teachers = (await api("/api/admin/teachers")).items;

              const assignRows = af.items.map(it =>
                el("div", { class: "row" }, [
                  el("div", { class: "field" }, `${it.period} · Sem ${it.semester} ${it.section} · ${it.subject_name || "—"}`),
                  el("div", { class: "field" }, [
                    el("select", {}, [
                      el("option", { value: "" }, "— Substitute —"),
                      ...teachers.map(t => el("option", { value: t.id }, t.name)),
                    ]),
                  ]),
                ])
              );

              const close = openModal("Assign Substitutes", [
                ...assignRows,
                el("div", { class: "row", style: "justify-content:flex-end;margin-top:12px" }, [
                  el("button", { class: "btn", onclick: async () => {
                    const assigns = [];
                    const selects = document.querySelectorAll(".modal select");
                    for (let i = 0; i < selects.length; i++) {
                      const v = selects[i].value;
                      if (v) assigns.push({
                        class_id: af.items[i].class_id,
                        day: af.items[i].day,
                        period: af.items[i].period,
                        substitute_teacher_id: parseInt(v),
                      });
                    }
                    await api(`/api/admin/leaves/${l.id}/assign`, { method: "POST", body: { assignments: assigns } });
                    toast("Assigned", "success"); close(); refresh();
                  } }, "Save"),
                  el("button", { class: "btn secondary", onclick: () => close() }, "Cancel"),
                ]),
              ]);
            } }, "Assign Substitutes"),
          ]),
        ]),
      ]);
      listHolder.appendChild(row);
    }
  }

  panel.appendChild(el("div", { class: "row" }, [el("div", { class: "field" }, [el("label", {}, "Filter"), filterSel]), el("div", { class: "field" }, [el("label", {}, "Search"), searchI]), el("button", { class: "btn", onclick: refresh }, "Refresh") ]));
  panel.appendChild(el("div", { style: "margin-top:12px" }, [listHolder]));
  refresh();
  content.appendChild(panel);
}

function renderAdminTimetable(entries, classId, refresh) {
  const wrap = el("div", { class: "tt-wrap" });
  const table = el("table", { class: "tt" });
  const thead = el("thead");
  thead.appendChild(el("tr", {}, [el("th", {}, "Day / Period"), ...META.periods.map(p => el("th", {}, p))]));
  table.appendChild(thead);

  const lookup = {};
  for (const e of entries) (lookup[`${e.day}|${e.period}`] = lookup[`${e.day}|${e.period}`] || []).push(e);

  const tbody = el("tbody");
  for (const day of META.days) {
    const row = el("tr", {}, [el("th", {}, day)]);
    let periodIndex = 0;
    while (periodIndex < META.periods.length) {
      const period = META.periods[periodIndex];
      const breakDef = getBreakDefinition(period);
      if (breakDef) {
        const startIndex = META.periods.indexOf(breakDef.start);
        const endIndex = META.periods.indexOf(breakDef.end);
        const colspan = Math.max(1, Math.abs(endIndex - startIndex) + 1);
        const td = el("td", { class: "cell break", colspan: String(colspan), style: "cursor:pointer" });
        td.appendChild(el("div", { class: "sub" }, breakCellText(period)));
        td.onclick = () => openAdminEntryModal(classId, { day, period: breakDef.start, entry_type: "break", note: breakDef.label }, refresh);
        row.appendChild(td);
        periodIndex += colspan;
        continue;
      }

      const items = lookup[`${day}|${period}`] || [];
      const span = getEntryCellSpan(lookup, day, periodIndex);
      const td = el("td", span > 1 ? { colspan: String(span) } : {});
      if (!items.length) {
        const empty = el("div", { class: "cell empty", style: "cursor:pointer" }, "+ Add");
        empty.onclick = () => openAdminEntryModal(classId, { day, period }, refresh);
        td.appendChild(empty);
      } else {
        const wrapper = el("div", { class: items.length > 1 ? "cell-multi" : "cell" });
        for (const it of items) {
          const c = el("div", { class: `cell ${it.entry_type}`, style: "cursor:pointer" });
          if (it.entry_type === "break") {
            c.appendChild(el("div", { class: "sub" }, it.note || (META.breaks && META.breaks[it.period]) || "BREAK"));
          } else {
            c.appendChild(el("div", { class: "sub" }, it.subject_name || "—"));
            if (it.teacher_name) c.appendChild(el("div", { class: "tea" }, it.teacher_name));
            if (it.entry_type !== "regular") {
              const badgeText = it.entry_type;
              c.appendChild(el("span", { class: "badge " + it.entry_type }, badgeText));
            }
          }
          c.onclick = () => openAdminEntryModal(classId, it, refresh);
          wrapper.appendChild(c);
        }
        td.appendChild(wrapper);
      }
      row.appendChild(td);
      periodIndex += span;
    }
    tbody.appendChild(row);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
  return wrap;
}

async function openAdminEntryModal(classId, entry, refresh) {
  const [subs, teachers] = await Promise.all([api("/api/admin/subjects"), api("/api/admin/teachers")]);
  const isEdit = entry && entry.id;

  const validPeriods = META.periods.filter(p => !isBreakPeriod(p));
  const daySel = el("select", {}, META.days.map(d => el("option", { value: d, selected: entry?.day === d ? "selected" : null }, d)));
  const periodSel = el("select", {}, validPeriods.map(p => el("option", { value: p, selected: entry?.period === p ? "selected" : null }, formatPeriodLabel(p))));
  // Duration selector: number of consecutive periods to occupy (1..max)
  function computeMaxDuration() {
    const pIdx = META.periods.indexOf(periodSel.value);
    if (pIdx === -1) return 1;
    let max = 1;
    for (let offset = 1; offset < 4; offset++) {
      const idx = pIdx + offset;
      if (idx >= META.periods.length) break;
      const per = META.periods[idx];
      if (isBreakPeriod(per)) break;
      max = offset + 1;
    }
    return Math.min(max, 6);
  }
  const durationSel = el("select", {}, []);
  function rebuildDurationOptions() {
    const max = computeMaxDuration();
    durationSel.innerHTML = "";
    for (let i = 1; i <= max; i++) {
      durationSel.appendChild(el("option", { value: String(i), selected: i === 1 ? "selected" : null }, i === 1 ? "1 period" : `${i} periods`));
    }
  }
  periodSel.addEventListener("change", () => { rebuildDurationOptions(); updatePreview(); });
  durationSel.addEventListener("change", updatePreview);
  const subSel = el("select", {}, [el("option", { value: "" }, "— Subject —"),
    ...subs.items.map(s => el("option", { value: s.id, selected: entry?.subject_id === s.id ? "selected" : null }, `${s.code} · ${s.name}`))]);

  // Live preview showing selected time + subject (e.g. "09:00–09:55 | CS101 · Computer Science")
  const previewText = el("div", { class: "preview-text" }, "");
  const preview = el("div", { class: "field" }, [el("label", {}, "Preview"), previewText]);
  function updatePreview() {
    const per = periodSel.value || "—";
    const dur = parseInt(durationSel.value || "1", 10);
    const pIdx = META.periods.indexOf(per);
    let timeText = per;
    if (pIdx !== -1 && dur > 1) {
      const endIdx = Math.min(META.periods.length - 1, pIdx + dur - 1);
      const endPer = META.periods[endIdx];
       // If periods are ranges like "09:00–09:50", extract start/end.
       const startPart = per.split(/[-–]/)[0].trim();
       const endPart = endPer.split(/[-–]/).pop().trim();
      timeText = `${startPart} to ${endPart}`;
    }
    const subjOpt = subSel.options[subSel.selectedIndex];
    const subjLabel = subjOpt ? subjOpt.textContent : "—";
    previewText.textContent = `${timeText} | ${subjLabel}`;
  }
  periodSel.addEventListener("change", updatePreview);
  subSel.addEventListener("change", updatePreview);
  // initialize preview
  rebuildDurationOptions();
  updatePreview();
  const teaSel = el("select", {}, [el("option", { value: "" }, "— Teacher —"),
    ...teachers.items.map(t => el("option", { value: t.id, selected: entry?.teacher_id === t.id ? "selected" : null }, t.name))]);
  const roomI = el("input", { type: "text", value: entry?.room || "", placeholder: "Room" });
  const typeSel = el("select", {}, ["regular", "extra", "substitution", "cancelled"].map(v =>
    el("option", { value: v, selected: entry?.entry_type === v ? "selected" : null }, v)));
  const noteI = el("input", { type: "text", value: entry?.note || "", placeholder: "Note" });
  const lockCb = el("input", { type: "checkbox", checked: entry?.locked ? "checked" : null });
  const overrideLockedCb = el("input", { type: "checkbox" });

  const close = openModal(isEdit ? "Edit Entry" : "Add Entry", [
    el("div", { class: "row" }, [
      el("div", { class: "field" }, [el("label", {}, "Day"), daySel]),
      el("div", { class: "field" }, [el("label", {}, "Period"), periodSel]),
      el("div", { class: "field" }, [el("label", {}, "Duration"), durationSel]),
    ]),
    el("div", { class: "field" }, [el("label", {}, "Subject"), subSel]),
    preview,
    el("div", { class: "field" }, [el("label", {}, "Teacher"), teaSel]),
    el("div", { class: "row" }, [
      el("div", { class: "field" }, [el("label", {}, "Room"), roomI]),
      el("div", { class: "field" }, [el("label", {}, "Type"), typeSel]),
    ]),
    el("div", { class: "field" }, [el("label", {}, "Note"), noteI]),
    el("div", { class: "field" }, [el("label", {}, "Locked"), lockCb, el("div", { class: "muted" }, "Locked entries won't be modified by auto-generate.")]),
    el("div", { class: "field" }, [el("label", {}, "Overwrite locked entries"), overrideLockedCb, el("div", { class: "muted" }, "If checked, admin may overwrite existing locked entries in target slots.")]),
    el("div", { class: "row", style: "margin-top:14px;justify-content:flex-end" }, [
      isEdit ? el("button", { class: "btn danger", onclick: async () => {
        if (!confirm("Delete this entry?")) return;
        try {
          await api("/api/admin/timetable/entry", { method: "DELETE", body: { id: entry.id } });
          toast("Timetable entry deleted", "success");
          close();
          refresh();
        } catch (e) { toast(e.message, "error"); }
      }, disabled: entry?.locked ? "disabled" : null }, entry?.locked ? "Locked" : "Delete") : null,
      el("button", { class: "btn", onclick: async () => {
        const dur = parseInt(durationSel.value || "1", 10);
        const pIdx = META.periods.indexOf(periodSel.value);
        const bodies = [];
        for (let off = 0; off < dur; off++) {
          const per = META.periods[pIdx + off];
          bodies.push({
            class_id: classId, day: daySel.value, period: per,
            subject_id: subSel.value ? parseInt(subSel.value) : null,
            teacher_id: teaSel.value ? parseInt(teaSel.value) : null,
            room: roomI.value, entry_type: typeSel.value, note: noteI.value,
            locked: lockCb.checked ? 1 : 0,
          });
        }
         try {
           // Multiple classes are allowed in one class/day/period slot. Each
           // entry is kept as its own record and rendered inside the same cell.
          if (isEdit) {
            await api("/api/admin/timetable/entry", { method: "PUT", body: { ...bodies[0], id: entry.id } });
          } else {
            await api("/api/admin/timetable/entry", { method: "POST", body: { entries: bodies } });
          }
          toast("Saved", "success"); close(); refresh();
        } catch (e) { toast(e.message, "error"); }
      }}, "Save"),
      el("button", { class: "btn secondary", onclick: () => close() }, "Cancel"),
    ]),
  ]);
}

// ============ MODAL ============
function openModal(title, children) {
  const bg = el("div", { class: "modal-bg" });
  const modal = el("div", { class: "modal" }, [el("h3", {}, title), ...children]);
  bg.appendChild(modal);
  bg.addEventListener("click", (e) => { if (e.target === bg) close(); });
  document.body.appendChild(bg);
  function close() { bg.remove(); }
  return close;
}

init();
