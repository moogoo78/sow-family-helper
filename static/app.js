(function () {
  "use strict";

  const loginScreen = document.getElementById("login-screen");
  const appScreen = document.getElementById("app-screen");
  const loginForm = document.getElementById("login-form");
  const loginPassword = document.getElementById("login-password");
  const loginError = document.getElementById("login-error");
  const searchInput = document.getElementById("search-input");
  const resultsEl = document.getElementById("results");
  const detailEl = document.getElementById("detail");
  const detailContent = document.getElementById("detail-content");
  const detailBack = document.getElementById("detail-back");
  const logoutBtn = document.getElementById("logout-btn");

  let people = [];
  let byId = new Map();
  let groups = [];
  let selectedGroup = null;
  let selectedCategory = null;
  let selectedTraining = null;
  let selectedBase = null;
  let selectedFamily = null;
  let newFamilyList = false;
  let currentThYear = null;
  let trainingList = false;
  let leaders = [];
  let leaderList = false;

  const CONTACT_LABELS = {
    mobile: "手機",
    phone: "市話",
    // Email 只有用管理密碼登入時才會出現在 payload 裡（見 server.py），
    // 一般登入拿到的資料根本沒有這個欄位，這裡也就不用另外判斷。
    email: "Email",
    line_id: "LINE",
    address: "地址",
  };
  const CONTACT_LINKS = { mobile: "tel", phone: "tel", email: "mailto" };
  // Non-staff section label per group -- 育成 has no kids, its plain
  // members are young adults, so it gets its own label instead of "小孩".
  const NON_STAFF_LABELS = { A: "小蟻", B: "小蜂", D: "小鹿", E: "小鷹", C: "育成大人" };

  function show(el) { el.classList.remove("hidden"); }
  function hide(el) { el.classList.add("hidden"); }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  // Single-character group labels (蟻/蜂/鹿/鷹) are short for "XX團"; multi-character
  // ones (e.g. 育成) are already the full name and shouldn't get a "團" suffix.
  function groupDisplayName(label) {
    if (!label) return "";
    return label.length === 1 ? `${label}團` : label;
  }

  // 蟻團・小蟻 -- the 職務 is dropped when there isn't one, or when it just
  // repeats the group name (育成's plain members would read 育成・育成).
  function groupText(group) {
    const name = groupDisplayName(group.label);
    if (!group.role || group.role === group.label) return name;
    return `${name}・${group.role}`;
  }

  async function loadMembers() {
    const res = await fetch("/api/members");
    if (res.status === 401) {
      show(loginScreen);
      hide(appScreen);
      return false;
    }
    const data = await res.json();
    people = data.people || [];
    byId = new Map(people.map((p) => [p.id, p]));
    groups = data.groups || [];
    leaders = data.leaders || [];
    currentThYear = data.current_th_year || null;
    selectedGroup = null;
    selectedCategory = null;
    selectedTraining = null;
    selectedBase = null;
    selectedFamily = null;
    newFamilyList = false;
    trainingList = false;
    leaderList = false;
    hide(loginScreen);
    show(appScreen);
    renderHome();
    return true;
  }

  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    hide(loginError);
    const password = loginPassword.value;
    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    if (res.ok) {
      loginPassword.value = "";
      await loadMembers();
    } else if (res.status === 429) {
      loginError.textContent = "嘗試次數過多，請稍後再試";
      show(loginError);
    } else {
      loginError.textContent = "密碼錯誤";
      show(loginError);
    }
  });

  // 現役團員。`people` also carries people who have left but have a 培訓紀錄
  // (see dataset.py) -- they belong in the 培訓 lists and nowhere else.
  function roster() {
    return people.filter((p) => p.active !== false);
  }

  // 自然名 + 本名 only -- the 家族名 shown next to each row is not searched.
  function matches(person, query) {
    if (!query) return true;
    const q = query.toLowerCase();
    return (
      (person.nickname || "").toLowerCase().includes(q) ||
      (person.name || "").toLowerCase().includes(q)
    );
  }

  // Rows show the 自然名 only -- the real name is for the detail page.
  // Search still matches on it (see matches()), it just isn't printed.
  function memberRow(p, subtitle) {
    const former = p.active === false ? " former" : "";
    return `
      <div class="result-item${former}" data-id="${p.id}">
        <span class="nickname">${escapeHtml(p.nickname || "")}</span>
        <span class="family">${escapeHtml(subtitle)}</span>
      </div>`;
  }

  function renderResults(query) {
    const filtered = roster().filter((p) => matches(p, query));
    if (filtered.length === 0) {
      resultsEl.innerHTML = '<div class="empty-state">找不到符合的人</div>';
      return;
    }
    resultsEl.innerHTML = filtered
      .map((p) => memberRow(p, (p.family && p.family.name) || ""))
      .join("");
  }

  function renderGroupCards() {
    if (groups.length === 0) {
      resultsEl.innerHTML = '<div class="empty-state">目前沒有分團資料</div>';
      return;
    }
    resultsEl.innerHTML = groups
      .map((g) => {
        const counts = groupCategories(g.code)
          .map(({ category, label }) => `${escapeHtml(label)} ${groupMembers(g.code, category).length}`)
          .join("・");
        return `
          <div class="group-card" data-code="${g.code}">
            <span class="group-name">${escapeHtml(groupDisplayName(g.label))}</span>
            <span class="group-counts">${counts}</span>
          </div>`;
      })
      .join("");
    if (trainingIndex().size) {
      resultsEl.innerHTML += `
        <div class="group-card group-card-alt" data-view="trainings">
          <span class="group-name">培訓紀錄</span>
        </div>`;
    }
    if (newFamilies().size) {
      resultsEl.innerHTML += `
        <div class="group-card group-card-fam" data-view="newfamilies">
          <span class="group-name">${currentThYear} 年新家庭</span>
        </div>`;
    }
    if (leaders.length) {
      resultsEl.innerHTML += `
        <div class="group-card group-card-lead" data-view="leaders">
          <span class="group-name">歷年團會長</span>
          <span class="group-counts">第 1 - ${currentThYear} 年</span>
        </div>`;
    }
  }

  function groupMembers(code, category) {
    return roster().filter(
      (p) =>
        p.current_group &&
        p.current_group.code === code &&
        (!category || p.current_group.category === category)
    );
  }

  // 工作人員 list order: 團長 -> 副團長 -> 導引員 -> 攝影官 -> everyone else.
  // Roles are stored group-prefixed and abbreviated (蟻團長, 蜂副團, 鹿導,
  // 鷹指導, 蟻攝影, 育副會-蟻 ...), so match the distinguishing substring.
  // 育成 uses 會長/副會長 where the other groups use 團長/副團長.
  const STAFF_ROLE_RANKS = [
    [/副團|副會/, 1], // tested before 團長/會長 so 副X doesn't rank as the head
    [/團長|會長/, 0],
    [/導/, 2],
    [/攝影/, 3],
  ];

  // 複式團長 spans every group rather than leading 育成, so it goes last in
  // the list instead of taking the 團長 slot.
  const CROSS_GROUP_ROLE = /複式/;

  function staffRank(role) {
    role = role || "";
    if (CROSS_GROUP_ROLE.test(role)) return STAFF_ROLE_RANKS.length + 1;
    for (const [pattern, rank] of STAFF_ROLE_RANKS) {
      if (pattern.test(role)) return rank;
    }
    return STAFF_ROLE_RANKS.length;
  }

  // The two categories a group is split into. "小孩" is the stored category
  // value; only its display label varies per group (see NON_STAFF_LABELS).
  function groupCategories(code) {
    return [
      { category: "工作人員", label: "工作人員" },
      { category: "小孩", label: NON_STAFF_LABELS[code] || "小孩" },
    ];
  }

  function renderGroupCategories(code) {
    const group = groups.find((g) => g.code === code);
    const cards = groupCategories(code)
      .map(({ category, label }) => {
        const count = groupMembers(code, category).length;
        return `
          <div class="group-card category-tile" data-category="${escapeHtml(category)}">
            <span class="group-name">${escapeHtml(label)}</span>
            <span class="group-counts">${count} 人</span>
          </div>`;
      })
      .join("");

    resultsEl.innerHTML = `
      <div class="group-back" data-to="groups">&larr; 所有分團</div>
      <h2 class="group-title">${escapeHtml(group ? groupDisplayName(group.label) : "")}</h2>
      <div class="category-tiles">${cards}</div>`;
  }

  function renderCategoryMembers(code, category) {
    const group = groups.find((g) => g.code === code);
    const groupName = group ? groupDisplayName(group.label) : "";
    const entry = groupCategories(code).find((c) => c.category === category);
    const label = entry ? entry.label : category;
    const list = groupMembers(code, category);
    if (category === "工作人員") {
      // Array.prototype.sort is stable, so equal ranks keep the source order.
      list.sort((a, b) => staffRank(a.current_group.role) - staffRank(b.current_group.role));
    }

    resultsEl.innerHTML = `
      <div class="group-back" data-to="categories">&larr; ${escapeHtml(groupName)}</div>
      <h2 class="group-title">${escapeHtml(groupName)}・${escapeHtml(label)}<span class="count-badge">${list.length}</span></h2>
      <div class="category-card">
        ${list.map((p) => memberRow(p, p.current_group.role || "")).join("") || `<p class="hint">目前沒有${escapeHtml(label)}成員</p>`}
      </div>`;
  }

  // 培訓紀錄 -> the people who hold it. This one deliberately covers everyone
  // in the payload, people who have left included -- they took the same 基訓
  // and belong on its list. 現役的排前面，離團的排後面（灰色那些）。
  function trainingIndex() {
    const index = new Map();
    for (const p of [...people].sort((a, b) => (a.active === false) - (b.active === false))) {
      for (const t of p.trainings || []) {
        const name = (t.name || "").trim();
        // "-" is a placeholder, same as 職務 uses (see EMPTY_ROLES)
        if (!name || name === "-") continue;
        if (!index.has(name)) index.set(name, []);
        index.get(name).push(p);
      }
    }
    return index;
  }

  // "12 人" for a list of current members, "12 人・5 已離團" when the list
  // carries people who have left as well.
  function trainingCount(list) {
    const gone = list.filter((p) => p.active === false).length;
    return gone ? `${list.length} 人・${gone} 已離團` : `${list.length} 人`;
  }

  function memberSubtitle(p) {
    if (p.active === false) {
      const fam = (p.family && p.family.name) || "";
      const left = p.last_th_year ? `第 ${p.last_th_year} 年離團` : "已離團";
      return fam ? `${fam}・${left}` : left;
    }
    if (p.current_group) {
      return groupText(p.current_group);
    }
    return (p.family && p.family.name) || "";
  }

  // 上過X基 -- every 基訓 of one 團, whatever the region or 期別
  // (北蟻15基, 桃蟻1基, 宜蟻2基 all count as 蟻基). Only 基訓 carry a 團
  // character; 進訓, 山豬 and 解說員訓 never do.
  function baseTrainingGroups() {
    return groups.map((g) => ({ code: g.code, char: (g.label || "")[0] })).filter((g) => g.char);
  }

  function baseTrainingMembers(char, index) {
    const seen = new Set();
    const list = [];
    for (const [name, holders] of index) {
      if (!name.includes(char)) continue;
      for (const p of holders) {
        if (seen.has(p.id)) continue;
        seen.add(p.id);
        list.push(p);
      }
    }
    // 現役的排前面，離團的排後面（同 trainingIndex）
    return list.sort((a, b) => (a.active === false) - (b.active === false));
  }

  // Families whose join_th_year is this year -- 第 N 年新家庭.
  function newFamilies() {
    const index = new Map();
    for (const p of roster()) {
      const f = p.family;
      if (!f || !f.id || f.join_th_year !== currentThYear) continue;
      if (!index.has(f.id)) index.set(f.id, { name: f.name, members: [] });
      index.get(f.id).members.push(p);
    }
    return index;
  }

  function renderNewFamilyList() {
    const index = newFamilies();
    const cards = [...index.entries()]
      .sort((a, b) => a[1].name.localeCompare(b[1].name, "zh-Hant", { numeric: true }))
      .map(([id, fam]) => `
        <div class="group-card" data-family="${id}">
          <span class="group-name">${escapeHtml(fam.name)}</span>
          <span class="group-counts">${fam.members.length} 人</span>
        </div>`)
      .join("");
    resultsEl.innerHTML = `
      <div class="group-back" data-to="home">&larr; 所有分團</div>
      <h2 class="group-title">第 ${currentThYear} 年新家庭<span class="count-badge">${index.size}</span></h2>
      ${cards || '<div class="empty-state">今年沒有新家庭</div>'}`;
  }

  function renderFamilyMembers(id) {
    const fam = newFamilies().get(Number(id));
    if (!fam) return renderNewFamilyList();
    resultsEl.innerHTML = `
      <div class="group-back" data-to="newfamilies">&larr; 第 ${currentThYear} 年新家庭</div>
      <h2 class="group-title">${escapeHtml(fam.name)}<span class="count-badge">${fam.members.length}</span></h2>
      <div class="category-card">
        ${fam.members.map((p) => memberRow(p, memberSubtitle(p))).join("")}
      </div>`;
  }

  // 歷年團會長：一年一段，複式團長在最前面。人還在名單上的才點得進去
  // (一開始那幾年的團長有些已經離團，dataset.py 還是會送過來)。
  function renderLeaderList() {
    const years = leaders
      .map((y) => {
        const rows = y.leaders
          .map((l) => {
            const known = byId.has(l.person_id);
            const cls = `leader-row ${l.code ? `g-${l.code.toLowerCase()}` : "leader-cross"}`;
            const id = known ? ` data-id="${l.person_id}"` : "";
            return `
              <div class="${cls}${known ? "" : " unlinked"}"${id}>
                <span class="role">${escapeHtml(l.title)}</span>
                <span class="nickname">${escapeHtml(l.nickname || "")}</span>
              </div>`;
          })
          .join("");
        return `<h3 class="leader-year">第 ${y.th_year} 年</h3>${rows}`;
      })
      .join("");
    resultsEl.innerHTML = `
      <div class="group-back" data-to="home">&larr; 所有分團</div>
      <h2 class="group-title">歷年團會長</h2>
      ${years || '<div class="empty-state">沒有團會長紀錄</div>'}`;
  }

  function renderTrainingList() {
    const index = trainingIndex();
    // numeric: true so 北鹿6基 comes before 北鹿12基 rather than after it.
    const names = [...index.keys()].sort((a, b) =>
      a.localeCompare(b, "zh-Hant", { numeric: true })
    );
    const cards = names
      .map((name) => `
        <div class="group-card" data-training="${escapeHtml(name)}">
          <span class="group-name">${escapeHtml(name)}</span>
          <span class="group-counts">${trainingCount(index.get(name))}</span>
        </div>`)
      .join("");

    const summary = baseTrainingGroups()
      .map(({ code, char }) => {
        const list = baseTrainingMembers(char, index);
        if (!list.length) return "";
        return `
          <div class="group-card base-card g-${code.toLowerCase()}" data-base="${escapeHtml(char)}">
            <span class="group-name">上過${escapeHtml(char)}基</span>
            <span class="group-counts">${trainingCount(list)}</span>
          </div>`;
      })
      .join("");

    resultsEl.innerHTML = `
      <div class="group-back" data-to="home">&larr; 所有分團</div>
      <h2 class="group-title">培訓紀錄<span class="count-badge">${names.length}</span></h2>
      ${summary}
      ${cards || '<div class="empty-state">目前沒有培訓資料</div>'}`;
  }

  function renderBaseTrainingMembers(char) {
    const list = baseTrainingMembers(char, trainingIndex());
    resultsEl.innerHTML = `
      <div class="group-back" data-to="trainings">&larr; 所有培訓</div>
      <h2 class="group-title">上過${escapeHtml(char)}基<span class="count-badge">${list.length}</span></h2>
      <div class="category-card">
        ${list.map((p) => memberRow(p, memberSubtitle(p))).join("") || '<p class="hint">目前沒有人上過</p>'}
      </div>`;
  }

  function renderTrainingMembers(name) {
    const list = trainingIndex().get(name) || [];
    resultsEl.innerHTML = `
      <div class="group-back" data-to="trainings">&larr; 所有訓練</div>
      <h2 class="group-title">${escapeHtml(name)}<span class="count-badge">${list.length}</span></h2>
      <div class="category-card">
        ${list.map((p) => memberRow(p, memberSubtitle(p))).join("") || '<p class="hint">目前沒有人有這項訓練</p>'}
      </div>`;
  }

  function renderHome() {
    const query = searchInput.value.trim();
    if (query) {
      renderResults(query);
    } else if (selectedTraining) {
      renderTrainingMembers(selectedTraining);
    } else if (selectedBase) {
      renderBaseTrainingMembers(selectedBase);
    } else if (selectedFamily) {
      renderFamilyMembers(selectedFamily);
    } else if (newFamilyList) {
      renderNewFamilyList();
    } else if (trainingList) {
      renderTrainingList();
    } else if (leaderList) {
      renderLeaderList();
    } else if (selectedGroup && selectedCategory) {
      renderCategoryMembers(selectedGroup, selectedCategory);
    } else if (selectedGroup) {
      renderGroupCategories(selectedGroup);
    } else {
      renderGroupCards();
    }
  }

  resultsEl.addEventListener("click", (e) => {
    const card = e.target.closest(".group-card");
    if (card) {
      if (card.dataset.view === "trainings") trainingList = true;
      else if (card.dataset.view === "newfamilies") newFamilyList = true;
      else if (card.dataset.view === "leaders") leaderList = true;
      else if (card.dataset.family) selectedFamily = card.dataset.family;
      else if (card.dataset.base) selectedBase = card.dataset.base;
      else if (card.dataset.training) selectedTraining = card.dataset.training;
      else if (card.dataset.code) selectedGroup = card.dataset.code;
      else selectedCategory = card.dataset.category;
      renderHome();
      return;
    }
    const back = e.target.closest(".group-back");
    if (back) {
      if (back.dataset.to === "categories") {
        selectedCategory = null;
      } else if (back.dataset.to === "trainings") {
        selectedTraining = null;
        selectedBase = null;
      } else if (back.dataset.to === "newfamilies") {
        selectedFamily = null;
      } else {
        selectedGroup = null;
        selectedCategory = null;
        selectedTraining = null;
        selectedBase = null;
        selectedFamily = null;
        newFamilyList = false;
        trainingList = false;
        leaderList = false;
      }
      renderHome();
      return;
    }
    const leader = e.target.closest(".leader-row[data-id]");
    if (leader) {
      openDetail(Number(leader.dataset.id));
      return;
    }
    const item = e.target.closest(".result-item");
    if (item) {
      openDetail(Number(item.dataset.id));
    }
  });

  searchInput.addEventListener("input", () => renderHome());

  function contactRows(person) {
    return Object.keys(CONTACT_LABELS)
      .filter((key) => person[key])
      .map((key) => {
        const value = person[key];
        const linkKind = CONTACT_LINKS[key];
        // 電話要把空白、括號編掉；email 本身就是合法的 URI，用
        // encodeURIComponent 反而會把 @ 變成 %40。
        const href = linkKind === "mailto"
          ? `mailto:${encodeURI(value)}`
          : `${linkKind}:${encodeURIComponent(value)}`;
        const display = linkKind
          ? `<a href="${escapeHtml(href)}">${escapeHtml(value)}</a>`
          : escapeHtml(value);
        return `<div class="field-row"><span class="label">${CONTACT_LABELS[key]}</span><span>${display}</span></div>`;
      })
      .join("");
  }

  function renderProfile(person) {
    const rows = [];
    if (person.old_nickname) {
      rows.push(`<div class="field-row"><span class="label">舊自然名</span><span>${escapeHtml(person.old_nickname)}</span></div>`);
    }
    if (person.current_group) {
      const cg = person.current_group;
      rows.push(`<div class="field-row"><span class="label">分團</span><span>${escapeHtml(groupText(cg))}</span></div>`);
    }
    if (person.active === false) {
      const left = person.last_th_year ? `第 ${person.last_th_year} 年離團` : "已離團";
      rows.push(`<div class="field-row"><span class="label">狀態</span><span class="former-note">${left}</span></div>`);
    }
    if (person.first_th_year) {
      rows.push(`<div class="field-row"><span class="label">入團年</span><span>第 ${person.first_th_year} 年</span></div>`);
    }
    if (person.sow_number) {
      rows.push(`<div class="field-row"><span class="label">荒野編號</span><span><button type="button" class="reveal-btn" data-value="${escapeHtml(person.sow_number)}">顯示荒野編號</button></span></div>`);
    }
    rows.push(contactRows(person));

    return `
      <div class="profile-card">
        <h2>${escapeHtml(person.nickname || "")}</h2>
        <p class="subname">${escapeHtml(person.name || "")}</p>
        ${rows.join("")}
      </div>`;
  }

  function renderFamily(person) {
    if (!person.family) return "";
    const members = person.family_members
      .map((m) => {
        // 今年的分團．職務，跟在名字後面。沒有今年紀錄的人就不顯示。
        const cg = m.current_group;
        const group = cg
          ? `<span class="member-group">${escapeHtml(groupText(cg))}</span>`
          : "";
        return `
        <div class="family-member" data-id="${m.id}">
          <span class="relation">${escapeHtml(m.relation)}</span>
          <span class="nickname">${escapeHtml(m.nickname || "")}</span>
          ${group}
        </div>`;
      })
      .join("");
    return `
      <div class="section">
        <h3>家庭：${escapeHtml(person.family.name)}</h3>
        ${members || '<p class="hint">目前沒有其他登記的家庭成員</p>'}
      </div>`;
  }

  function renderFamilyHistory(person) {
    if (!person.family_history || person.family_history.length === 0) return "";
    const rows = person.family_history
      .map(
        (f) =>
          `<div class="past-family-row">${escapeHtml(f.name)}（第 ${f.join_th_year ?? "?"} 年 - 第 ${f.leave_th_year ?? "?"} 年）</div>`
      )
      .join("");
    return `<div class="section"><h3>曾屬家庭</h3>${rows}</div>`;
  }

  // "無" (and the odd "-") mean "no post that year" -- those rows carry no
  // information, so they stay out of the log.
  const EMPTY_ROLES = new Set(["無", "-", ""]);

  const GROUP_CLASS = { "蟻": "g-a", "蜂": "g-b", "育成": "g-c", "鹿": "g-d", "鷹": "g-e" };

  // Consecutive years in the same 團 with the same 職務 become one bar.
  function roleSegments(roles) {
    const segments = [];
    for (const r of [...roles].sort((a, b) => a.th_year - b.th_year)) {
      const last = segments[segments.length - 1];
      if (last && last.role === (r.role || "") && last.group === (r.group_label || "") &&
          last.end + 1 === r.th_year) {
        last.end = r.th_year;
      } else {
        segments.push({
          role: r.role || "",
          group: r.group_label || "",
          start: r.th_year,
          end: r.th_year,
        });
      }
    }
    return segments;
  }

  function renderRoleGantt(roles) {
    const segments = roleSegments(roles);
    if (segments.length === 0) return "";
    const first = Math.min(...segments.map((s) => s.start));
    const last = Math.max(...segments.map((s) => s.end));

    const axis = [];
    for (let y = first; y <= last; y++) axis.push(`<span>${y}</span>`);

    const bars = segments
      .map((s) => `
        <div class="gantt-label">${escapeHtml(s.role)}</div>
        <div class="gantt-track">
          <div class="gantt-bar ${GROUP_CLASS[s.group] || ""}"
               style="grid-column: ${s.start - first + 1} / span ${s.end - s.start + 1}"></div>
        </div>`)
      .join("");

    const legend = [...new Set(segments.map((s) => s.group))]
      .filter(Boolean)
      .map((g) => `<span class="gantt-key"><i class="${GROUP_CLASS[g] || ""}"></i>${escapeHtml(groupDisplayName(g))}</span>`)
      .join("");

    return `
      <div class="gantt-scroll">
        <div class="gantt" style="--years: ${last - first + 1}">
          <div class="gantt-label gantt-axis-label">第 N 年</div>
          <div class="gantt-track gantt-axis">${axis.join("")}</div>
          ${bars}
        </div>
      </div>
      <div class="gantt-legend">${legend}</div>`;
  }

  function renderRoles(person) {
    const roles = (person.roles || []).filter((r) => !EMPTY_ROLES.has((r.role || "").trim()));
    if (roles.length === 0) return "";
    const rows = roles
      .map((r) => {
        const group = r.group_label ? `${groupDisplayName(r.group_label)}　` : "";
        const remarks = [r.role_remark, r.remark].filter(Boolean).join("　");
        return `
          <div class="log-row">
            <div class="th-year">第 ${r.th_year} 年　${group}${escapeHtml(r.role || "")}</div>
            ${remarks ? `<div>${escapeHtml(remarks)}</div>` : ""}
          </div>`;
      })
      .join("");
    return `<div class="section"><h3>職務紀錄</h3>${rows}${renderRoleGantt(roles)}</div>`;
  }

  function renderTrainings(person) {
    const names = (person.trainings || [])
      .map((t) => (t.name || "").trim())
      .filter((name) => name && name !== "-");
    if (names.length === 0) return "";
    const rows = names
      .map((name) => `<div class="log-row log-link" data-training="${escapeHtml(name)}">${escapeHtml(name)}</div>`)
      .join("");
    return `<div class="section"><h3>培訓紀錄</h3>${rows}</div>`;
  }

  function openDetail(id) {
    const person = byId.get(id);
    if (!person) return;
    detailContent.innerHTML =
      renderProfile(person) +
      renderFamily(person) +
      renderFamilyHistory(person) +
      renderRoles(person) +
      renderTrainings(person);
    show(detailEl);
    detailEl.scrollTop = 0;
  }

  detailContent.addEventListener("click", (e) => {
    const reveal = e.target.closest(".reveal-btn");
    if (reveal) {
      // textContent, so the value is never parsed as markup
      reveal.replaceWith(document.createTextNode(reveal.dataset.value || ""));
      return;
    }
    const training = e.target.closest("[data-training]");
    if (training) {
      hide(detailEl);
      searchInput.value = "";
      selectedGroup = null;
      selectedCategory = null;
      trainingList = true;
      selectedBase = null;
      selectedFamily = null;
      newFamilyList = false;
      selectedTraining = training.dataset.training;
      renderHome();
      return;
    }
    const item = e.target.closest(".family-member");
    if (!item) return;
    openDetail(Number(item.dataset.id));
  });

  detailBack.addEventListener("click", () => hide(detailEl));

  logoutBtn.addEventListener("click", async () => {
    await fetch("/api/logout", { method: "POST" });
    people = [];
    byId = new Map();
    groups = [];
    leaders = [];
    leaderList = false;
    selectedGroup = null;
    selectedCategory = null;
    selectedTraining = null;
    selectedBase = null;
    selectedFamily = null;
    trainingList = false;
    newFamilyList = false;
    searchInput.value = "";
    resultsEl.innerHTML = "";
    hide(detailEl);
    hide(appScreen);
    show(loginScreen);
    loginPassword.focus();
  });

  loadMembers();
})();
