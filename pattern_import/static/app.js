const FETCH_FAILED = "This address did not come back. Check it, or paste the pattern.";

const tabs = [...document.querySelectorAll("[role='tab']")];
const urlPanel = document.getElementById("url-panel");
const filePanel = document.getElementById("file-panel");
const control = document.querySelector(".control");
const source = document.getElementById("source");
const readingWrap = document.getElementById("reading-wrap");
const notice = document.getElementById("notice");
const reading = document.getElementById("reading");
const partsEl = document.getElementById("parts");
const accept = document.getElementById("accept");
const discard = document.getElementById("discard");
const another = document.getElementById("another");
const settled = document.getElementById("settled");
const urlInput = document.getElementById("url");
const fileInput = document.getElementById("file");
const fileLabel = document.getElementById("file-label");

let tab = "paste";
let phase = "empty";
let token = 0;
let parts = null;

tabs.forEach((button, index) => {
  button.addEventListener("click", () => selectTab(nameOf(button)));
  button.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    event.preventDefault();
    const next = event.key === "ArrowRight" ? (index + 1) % tabs.length : (index + tabs.length - 1) % tabs.length;
    tabs[next].focus();
    selectTab(nameOf(tabs[next]));
  });
});

function nameOf(button) {
  if (button.id === "tab-url") return "url";
  if (button.id === "tab-file") return "file";
  return "paste";
}

function selectTab(name) {
  tab = name;
  render();
  if (name === "url") urlInput.focus();
  if (name === "file") fileInput.focus();
}

urlPanel.addEventListener("submit", (event) => {
  event.preventDefault();
  const url = urlInput.value.trim();
  if (!url) return;
  begin(async () => {
    const response = await fetch("/fetch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    return response.json();
  });
});

fileInput.addEventListener("change", () => {
  const file = fileInput.files && fileInput.files[0];
  if (!file) return;
  fileLabel.textContent = file.name;
  begin(async () => {
    const response = await fetch("/file", {
      method: "POST",
      headers: {
        "Content-Type": file.type || "application/octet-stream",
        "X-Filename": encodeURIComponent(file.name),
      },
      body: file,
    });
    return response.json();
  });
});

reading.addEventListener("input", () => {
  if (phase === "accepted" || phase === "working") return;
  fit(reading);
  if (phase === "empty" || phase === "failed") {
    phase = reading.value.trim() ? "ready" : "empty";
    source.textContent = phase === "ready" ? "Pasted" : "";
  }
  render();
});

accept.addEventListener("click", () => {
  if (!hasInput()) return;
  phase = "accepted";
  render();
});

discard.addEventListener("click", reset);
another.addEventListener("click", reset);

function hasInput() {
  if (parts && parts.some((part) => part.kind === "image" && part.src)) return true;
  if (parts) return parts.some((part) => part.kind === "text" && part.text.trim());
  return reading.value.trim() !== "";
}

function overlaps(band, part) {
  if (part.page == null || band.page == null || part.page !== band.page) return false;
  if (part.top == null || part.height == null) return false;
  return part.top <= band.bottom && part.top + part.height >= band.top;
}

function columnsOf(items) {
  const sorted = [...items].sort((a, b) => a.left - b.left || a.top - b.top);
  const columns = [];
  sorted.forEach((part) => {
    const column = columns[columns.length - 1];
    const overlapsX = column && part.left < column.right && part.left + part.width > column.left;
    if (!overlapsX) {
      columns.push({
        left: part.left,
        right: part.left + part.width,
        width: part.width,
        parts: [part],
      });
      return;
    }
    column.parts.push(part);
    column.left = Math.min(column.left, part.left);
    column.right = Math.max(column.right, part.left + part.width);
    column.width = column.right - column.left;
  });
  columns.forEach((column) => column.parts.sort((a, b) => a.top - b.top));
  return columns;
}

function closeBand(row, band) {
  if (!row || !band || band.parts.length < 2) return;
  const columns = columnsOf(band.parts);
  const sum = columns.reduce((total, column) => total + (column.width || 1), 0);
  row.replaceChildren();
  columns.forEach((column) => {
    const stack = document.createElement("div");
    stack.className = "stack";
    stack.style.width = `${(column.width / sum) * 100}%`;
    column.parts.forEach((part) => {
      const img = document.createElement("img");
      img.src = part.src;
      img.alt = "";
      stack.append(img);
    });
    row.append(stack);
  });
}

function showParts(list) {
  parts = list;
  partsEl.replaceChildren();
  let row = null;
  let band = null;
  list.forEach((part) => {
    if (part.kind === "text") {
      closeBand(row, band);
      row = null;
      band = null;
      const area = document.createElement("textarea");
      area.value = part.text || "";
      area.rows = 2;
      area.spellcheck = false;
      area.setAttribute("aria-label", "Reading");
      area.addEventListener("input", () => {
        part.text = area.value;
        if (phase === "accepted" || phase === "working") return;
        fit(area);
        phase = hasInput() ? "ready" : "empty";
        render();
      });
      partsEl.append(area);
      return;
    }
    if (part.kind !== "image" || !part.src) return;
    if (!band || !overlaps(band, part)) {
      closeBand(row, band);
      row = document.createElement("div");
      row.className = "band single";
      partsEl.append(row);
      band = {
        page: part.page,
        top: part.top,
        bottom: part.top + part.height,
        parts: [],
      };
    } else {
      row.classList.remove("single");
      band.top = Math.min(band.top, part.top);
      band.bottom = Math.max(band.bottom, part.top + part.height);
    }
    band.parts.push(part);
    const img = document.createElement("img");
    img.src = part.src;
    img.alt = "";
    row.append(img);
  });
  closeBand(row, band);
}

function fit(area, floorRows = 8) {
  const lines = area.value ? area.value.split("\n").length : 1;
  area.rows = Math.max(floorRows, lines);
  area.style.height = "auto";
  const floor = area.getBoundingClientRect().height;
  area.style.height = `${Math.max(floor, area.scrollHeight)}px`;
  if (area.scrollHeight > area.clientHeight) {
    area.style.height = `${area.scrollHeight}px`;
  }
}

window.addEventListener("resize", () => {
  if (!reading.hidden) fit(reading);
  if (!partsEl.hidden) partsEl.querySelectorAll("textarea").forEach((area) => fit(area, 1));
});

function sheet() {
  render();
  if (!reading.hidden) fit(reading);
  if (!partsEl.hidden) partsEl.querySelectorAll("textarea").forEach((area) => fit(area, 1));
}

async function begin(run) {
  const mine = ++token;
  phase = "working";
  parts = null;
  partsEl.replaceChildren();
  reading.value = "";
  source.textContent = "";
  notice.textContent = "Reading it…";
  render();
  let payload;
  try {
    payload = await run();
  } catch {
    payload = { ok: false, message: FETCH_FAILED };
  }
  if (mine !== token) return;
  if (!payload.ok) {
    phase = "failed";
    notice.textContent = payload.message || FETCH_FAILED;
    render();
    return;
  }
  phase = "ready";
  source.textContent = payload.source || "";
  const pictures = payload.parts && payload.parts.some((part) => part.kind === "image");
  if (pictures) {
    showParts(payload.parts);
    reading.value = "";
  } else {
    parts = null;
    partsEl.replaceChildren();
    reading.value = payload.reading || "";
  }
  sheet();
}

function reset() {
  token += 1;
  tab = "paste";
  phase = "empty";
  parts = null;
  partsEl.replaceChildren();
  source.textContent = "";
  notice.textContent = "";
  reading.value = "";
  urlInput.value = "";
  fileInput.value = "";
  fileLabel.textContent = "Choose a PDF or TXT file";
  sheet();
  reading.focus();
}

function render() {
  tabs.forEach((button) => {
    const on = nameOf(button) === tab;
    button.setAttribute("aria-selected", on ? "true" : "false");
    button.tabIndex = on ? 0 : -1;
  });
  urlPanel.hidden = tab !== "url";
  filePanel.hidden = tab !== "file";
  control.classList.toggle("on", tab !== "paste");

  const pastePanel = tab === "paste" && phase !== "working";
  if (pastePanel) {
    readingWrap.setAttribute("role", "tabpanel");
    readingWrap.setAttribute("aria-labelledby", "tab-paste");
  } else {
    readingWrap.removeAttribute("role");
    readingWrap.removeAttribute("aria-labelledby");
  }

  source.hidden = source.textContent.trim() === "";

  const showNotice = phase === "working" || phase === "failed";
  notice.hidden = !showNotice;
  const split = parts !== null;
  reading.hidden = split || (showNotice && tab !== "paste");
  if (phase === "working") reading.hidden = true;
  partsEl.hidden = !split || phase === "working" || (showNotice && tab !== "paste");
  reading.readOnly = phase === "accepted";
  partsEl.querySelectorAll("textarea").forEach((area) => {
    area.readOnly = phase === "accepted";
  });

  const accepted = phase === "accepted";
  settled.hidden = !accepted;
  accept.hidden = accepted;
  discard.hidden = accepted;
  another.hidden = !accepted;
  accept.disabled = phase !== "ready" || !hasInput();
  discard.disabled = phase === "empty";
}

render();
