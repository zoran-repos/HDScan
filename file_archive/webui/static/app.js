(() => {
  "use strict";

  const diskBar = document.getElementById("disk-bar");
  const breadcrumb = document.getElementById("breadcrumb");
  const foldersBody = document.getElementById("folders-body");
  const filesBody = document.getElementById("files-body");
  const paneFolders = document.getElementById("pane-folders");
  const paneFiles = document.getElementById("pane-files");
  const detailBar = document.getElementById("detail-bar");
  const searchInput = document.getElementById("search-input");
  const searchFiltersEl = document.getElementById("search-filters");

  const editOverlay = document.getElementById("disk-edit-overlay");
  const editLabelInput = document.getElementById("disk-edit-label");
  const editDescriptionInput = document.getElementById("disk-edit-description");
  const editSaveBtn = document.getElementById("disk-edit-save");
  const editCancelBtn = document.getElementById("disk-edit-cancel");

  const state = {
    disks: [],
    currentDiskId: null,
    currentPath: "",
    parentPath: null,
    folderRows: [],   // [{kind:'up'|'dir', ...}]
    fileRows: [],     // [{kind:'file', ...}]
    selectedFolder: -1,
    selectedFile: -1,
    activePane: "folders", // "folders" | "files"
    searchMode: false,
    fileRowsAll: [],      // unfiltered files for the current context (folder or search results)
    categoryFilter: null, // e.g. "Image" - narrows fileRowsAll for display in the files pane
    lastSearchQuery: "",
    editingDiskId: null,
  };

  async function fetchJson(url, options) {
    const res = await fetch(url, options);
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.error || `HTTP ${res.status}`);
    }
    return res.json();
  }

  function postJson(url, payload) {
    return fetchJson(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  async function loadDisks() {
    state.disks = await fetchJson("/api/disks");
    renderDiskBar();
  }

  function renderDiskBar() {
    diskBar.innerHTML = "";
    state.disks.forEach((d) => {
      const group = document.createElement("div");
      group.className = "disk-group" + (d.disk_id === state.currentDiskId ? " active" : "");

      const btn = document.createElement("button");
      btn.className = "disk-btn";
      btn.title = d.description || "";
      btn.innerHTML =
        `${escapeHtml(d.label)} <span class="n">[${d.volume_serial}] &middot; ${d.file_count} &middot; ${d.size_human}</span>` +
        (d.description ? `<span class="d">${escapeHtml(d.description)}</span>` : "");
      btn.addEventListener("click", () => selectDisk(d.disk_id));

      const editBtn = document.createElement("button");
      editBtn.className = "disk-edit-btn";
      editBtn.type = "button";
      editBtn.title = "Uredi naziv i opis";
      editBtn.textContent = "✎";
      editBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        openEditModal(d);
      });

      group.append(btn, editBtn);
      diskBar.appendChild(group);
    });
  }

  function openEditModal(disk) {
    state.editingDiskId = disk.disk_id;
    editLabelInput.value = disk.label === "(unlabeled)" ? "" : disk.label;
    editDescriptionInput.value = disk.description || "";
    editOverlay.classList.remove("hidden");
    editLabelInput.focus();
    editLabelInput.select();
  }

  function closeEditModal() {
    state.editingDiskId = null;
    editOverlay.classList.add("hidden");
  }

  async function saveEditModal() {
    if (state.editingDiskId == null) return;
    const updated = await postJson(`/api/disks/update?disk_id=${state.editingDiskId}`, {
      label: editLabelInput.value,
      description: editDescriptionInput.value,
    });
    const idx = state.disks.findIndex((d) => d.disk_id === updated.disk_id);
    if (idx !== -1) state.disks[idx] = updated;
    closeEditModal();
    renderDiskBar();
  }

  editSaveBtn.addEventListener("click", () => {
    saveEditModal().catch((err) => {
      detailBar.textContent = `Greška pri čuvanju: ${err.message}`;
    });
  });
  editCancelBtn.addEventListener("click", closeEditModal);
  editOverlay.addEventListener("click", (e) => {
    if (e.target === editOverlay) closeEditModal();
  });

  async function selectDisk(diskId) {
    state.currentDiskId = diskId;
    state.currentPath = "";
    state.searchMode = false;
    searchInput.value = "";
    renderDiskBar();
    await loadFolder(null);
  }

  async function loadFolder(folder) {
    if (state.currentDiskId == null) return;
    const params = new URLSearchParams({ disk_id: state.currentDiskId });
    if (folder) params.set("folder", folder);
    const data = await fetchJson(`/api/browse?${params.toString()}`);
    state.currentPath = data.current_path;
    state.parentPath = data.parent_path;
    state.searchMode = false;

    const folderRows = [];
    if (data.current_path) folderRows.push({ kind: "up", name: ".. (nazad)" });
    data.folders.forEach((f) => folderRows.push({ kind: "dir", ...f }));

    state.folderRows = folderRows;
    state.selectedFolder = folderRows.length ? 0 : -1;
    state.activePane = "folders";

    state.fileRowsAll = data.files;
    state.categoryFilter = null;

    renderBreadcrumb();
    applyCategoryFilter(); // sets fileRows, renders chips, and renders both panes
  }

  async function runSearch(query) {
    if (state.currentDiskId == null) return;
    if (!query) {
      await loadFolder(state.currentPath || null);
      return;
    }
    const params = new URLSearchParams({ disk_id: state.currentDiskId, q: query });
    const results = await fetchJson(`/api/search?${params.toString()}`);
    state.searchMode = true;
    state.folderRows = [];
    state.selectedFolder = -1;
    state.activePane = "files";
    state.fileRowsAll = results;
    state.categoryFilter = null;
    state.lastSearchQuery = query;
    applyCategoryFilter();
    updateSearchBreadcrumb();
  }

  function renderCategoryChips() {
    searchFiltersEl.innerHTML = "";
    if (!state.fileRowsAll.length) return;

    const counts = {};
    state.fileRowsAll.forEach((r) => {
      counts[r.category] = (counts[r.category] || 0) + 1;
    });
    const categories = Object.keys(counts).sort();
    if (categories.length < 2) return; // nothing meaningful to filter by

    const allBtn = document.createElement("button");
    allBtn.type = "button";
    allBtn.className = "filter-chip" + (state.categoryFilter === null ? " active" : "");
    allBtn.textContent = `Sve (${state.fileRowsAll.length})`;
    allBtn.addEventListener("click", () => setCategoryFilter(null));
    searchFiltersEl.appendChild(allBtn);

    categories.forEach((cat) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className =
        `filter-chip cat-${cat.toLowerCase()}` + (state.categoryFilter === cat ? " active" : "");
      btn.textContent = `${cat} (${counts[cat]})`;
      btn.addEventListener("click", () => setCategoryFilter(cat));
      searchFiltersEl.appendChild(btn);
    });
  }

  function setCategoryFilter(category) {
    state.categoryFilter = category;
    applyCategoryFilter();
    if (state.searchMode) updateSearchBreadcrumb();
  }

  function applyCategoryFilter() {
    const filtered = state.categoryFilter
      ? state.fileRowsAll.filter((r) => r.category === state.categoryFilter)
      : state.fileRowsAll;
    state.fileRows = filtered.map((r) => ({ kind: "file", ...r }));
    state.selectedFile = state.fileRows.length ? 0 : -1;

    renderCategoryChips();
    renderPanes();
  }

  function updateSearchBreadcrumb() {
    const label = state.categoryFilter ? ` &middot; ${state.categoryFilter}` : "";
    breadcrumb.innerHTML =
      `Pretraga: "${escapeHtml(state.lastSearchQuery)}"${label} — ${state.fileRows.length} od ${state.fileRowsAll.length} rezultat(a)`;
  }

  function renderBreadcrumb() {
    breadcrumb.innerHTML = "";
    const disk = state.disks.find((d) => d.disk_id === state.currentDiskId);
    const root = document.createElement("span");
    root.className = "seg";
    root.textContent = disk ? disk.label : "disk";
    root.addEventListener("click", () => loadFolder(null));
    breadcrumb.appendChild(root);

    if (!state.currentPath) return;
    const parts = state.currentPath.split("\\").filter(Boolean);
    let acc = [];
    parts.forEach((part) => {
      acc.push(part);
      const sep = document.createElement("span");
      sep.className = "sep";
      sep.textContent = "›";
      breadcrumb.appendChild(sep);

      const seg = document.createElement("span");
      seg.className = "seg";
      seg.textContent = part;
      const target = acc.join("\\");
      seg.addEventListener("click", () => loadFolder(target));
      breadcrumb.appendChild(seg);
    });
  }

  function renderPanes() {
    paneFolders.classList.toggle("active-pane", state.activePane === "folders");
    paneFiles.classList.toggle("active-pane", state.activePane === "files");

    // --- folders pane ---
    if (!state.folderRows.length) {
      foldersBody.innerHTML = `<tr><td class="empty" colspan="2">${state.searchMode ? "&nbsp;" : "Nema podfoldera."}</td></tr>`;
    } else {
      foldersBody.innerHTML = "";
      state.folderRows.forEach((row, i) => {
        const tr = document.createElement("tr");
        tr.className = "row" + (i === state.selectedFolder ? " selected" : "");
        const nameTd = document.createElement("td");
        nameTd.className = "col-name is-dir";
        const icon = row.kind === "up" ? "←" : "▸";
        nameTd.innerHTML = `<span class="icon">${icon}</span>${escapeHtml(row.name)}`;
        const countTd = document.createElement("td");
        countTd.className = "col-size";
        countTd.textContent = row.kind === "dir" ? `${row.file_count}` : "";
        tr.append(nameTd, countTd);
        tr.addEventListener("click", () => {
          state.activePane = "folders";
          state.selectedFolder = i;
          renderPanes();
        });
        tr.addEventListener("dblclick", () => openFolderRow(row));
        foldersBody.appendChild(tr);
      });
    }

    // --- files pane ---
    if (!state.fileRows.length) {
      filesBody.innerHTML = `<tr><td class="empty" colspan="4">Nema fajlova ovde.</td></tr>`;
    } else {
      filesBody.innerHTML = "";
      state.fileRows.forEach((row, i) => {
        const tr = document.createElement("tr");
        tr.className = "row" + (i === state.selectedFile ? " selected" : "");
        const nameTd = document.createElement("td");
        nameTd.className = "col-name";
        nameTd.innerHTML = `<span class="icon">•</span>${escapeHtml(row.name)}`;
        const catTd = document.createElement("td");
        catTd.className = "col-cat";
        catTd.innerHTML = `<span class="cat cat-${row.category.toLowerCase()}">${row.category}</span>`;
        const sizeTd = document.createElement("td");
        sizeTd.className = "col-size";
        sizeTd.textContent = row.size_human;
        const dateTd = document.createElement("td");
        dateTd.className = "col-date";
        dateTd.textContent = (row.modified_date || "").slice(0, 19).replace("T", " ");
        tr.append(nameTd, catTd, sizeTd, dateTd);
        tr.addEventListener("click", () => {
          state.activePane = "files";
          state.selectedFile = i;
          renderPanes();
        });
        tr.addEventListener("dblclick", () => openFileRow(row));
        filesBody.appendChild(tr);
      });
    }

    const selFolderEl = foldersBody.querySelector("tr.selected");
    if (selFolderEl) selFolderEl.scrollIntoView({ block: "nearest" });
    const selFileEl = filesBody.querySelector("tr.selected");
    if (selFileEl) selFileEl.scrollIntoView({ block: "nearest" });

    updateDetailBar();
  }

  function updateDetailBar() {
    if (state.activePane === "folders") {
      const row = state.folderRows[state.selectedFolder];
      if (!row || row.kind === "up") { detailBar.textContent = ""; return; }
      detailBar.innerHTML = `<b>${escapeHtml(row.name)}</b> — folder, ${row.file_count} fajl(ova), ${row.size_human}`;
      return;
    }
    const row = state.fileRows[state.selectedFile];
    if (!row) { detailBar.textContent = ""; return; }
    detailBar.innerHTML = `<b>${escapeHtml(row.path)}</b> — ${row.size_human}${row.hash ? " &middot; hash: " + row.hash.slice(0, 16) + "…" : ""}`;
  }

  async function openFolderRow(row) {
    if (row.kind === "up") {
      if (state.parentPath === null) {
        state.currentDiskId = null;
        renderDiskBar();
        breadcrumb.innerHTML = "";
        state.folderRows = [];
        state.fileRows = [];
        state.fileRowsAll = [];
        state.categoryFilter = null;
        searchFiltersEl.innerHTML = "";
        foldersBody.innerHTML = `<tr><td class="empty" colspan="2">Izaberi disk gore.</td></tr>`;
        filesBody.innerHTML = `<tr><td class="empty" colspan="4">&nbsp;</td></tr>`;
        detailBar.textContent = "";
        return;
      }
      await loadFolder(state.parentPath || null);
      return;
    }
    await loadFolder(row.path);
  }

  async function openFileRow(row) {
    detailBar.innerHTML = `Otvaram Windows Explorer za <b>${escapeHtml(row.name)}</b>...`;
    try {
      await postJson("/api/reveal", { path: row.path });
      updateDetailBar();
    } catch (err) {
      detailBar.innerHTML = `<b>Ne mogu da otvorim:</b> ${escapeHtml(err.message)}`;
    }
  }

  document.addEventListener("keydown", (e) => {
    if (!editOverlay.classList.contains("hidden")) {
      if (e.key === "Escape") closeEditModal();
      return; // modal is open - don't let pane shortcuts fire underneath it
    }
    if (document.activeElement === searchInput) return;

    if (e.key === "Tab") {
      e.preventDefault();
      state.activePane = state.activePane === "folders" ? "files" : "folders";
      renderPanes();
      return;
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const delta = e.key === "ArrowDown" ? 1 : -1;
      if (state.activePane === "folders" && state.folderRows.length) {
        state.selectedFolder = Math.min(Math.max(state.selectedFolder + delta, 0), state.folderRows.length - 1);
      } else if (state.activePane === "files" && state.fileRows.length) {
        state.selectedFile = Math.min(Math.max(state.selectedFile + delta, 0), state.fileRows.length - 1);
      }
      renderPanes();
      return;
    }
    if (e.key === "Enter") {
      if (state.activePane === "folders") {
        const row = state.folderRows[state.selectedFolder];
        if (row) openFolderRow(row);
      } else {
        const row = state.fileRows[state.selectedFile];
        if (row) openFileRow(row);
      }
      return;
    }
    if (e.key === "Backspace") {
      e.preventDefault();
      if (!state.searchMode && state.currentPath) openFolderRow({ kind: "up" });
      return;
    }
    if (e.key === "F5") {
      e.preventDefault();
      if (!state.searchMode) loadFolder(state.currentPath || null);
    }
  });

  let searchTimer = null;
  searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      runSearch(searchInput.value.trim());
    } else if (e.key === "Escape") {
      searchInput.value = "";
      loadFolder(state.currentPath || null);
    }
  });
  searchInput.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => runSearch(searchInput.value.trim()), 400);
  });

  loadDisks();
})();
