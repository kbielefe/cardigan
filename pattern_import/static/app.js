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

function partHasWords(part) {
  if (part.kind === "image" && part.src) return true;
  if (part.kind === "text" && part.text.trim()) return true;
  if (part.kind !== "grid") return false;
  return (part.cells || []).some((cell) =>
    (cell.kind === "image" && cell.src) || (cell.kind === "text" && cell.text.trim())
  );
}

function hasInput() {
  if (parts) return parts.some(partHasWords);
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
    column.parts.forEach((part) => appendPicture(stack, part));
    row.append(stack);
  });
}

function renderChart(chart) {
  if (!chart || !chart.grid || !chart.grid.length || !chart.grid[0].length) return null;
  const cols = chart.grid[0].length;
  const box = document.createElement("div");
  box.className = "chart";
  box.style.gridTemplateColumns = `repeat(${cols}, 18px)`;
  box.setAttribute("role", "img");
  box.setAttribute("aria-label", `Chart, ${chart.grid.length} rows of ${cols}`);
  chart.grid.forEach((row) => {
    row.forEach((index) => {
      const square = document.createElement("span");
      square.style.background = (chart.colors && chart.colors[index]) || "transparent";
      box.append(square);
    });
  });
  return box;
}

function appendPicture(parent, part) {
  const img = document.createElement("img");
  img.src = part.src;
  img.alt = "";
  const chart = renderChart(part.chart);
  if (!chart) {
    parent.append(img);
    return;
  }
  const block = document.createElement("div");
  block.className = "with-chart";
  block.append(img, chart);
  parent.append(block);
}

function renderGrid(grid) {
  const box = document.createElement("div");
  box.className = "grid";
  const width = grid.width || 1;
  const height = grid.height || 1;
  box.style.aspectRatio = `${width} / ${height}`;
  const charts = [];
  (grid.cells || []).forEach((cell) => {
    const el = cell.kind === "image" ? document.createElement("img") : document.createElement("textarea");
    el.className = "cell";
    el.style.left = `${((cell.left - grid.left) / width) * 100}%`;
    el.style.top = `${((cell.top - grid.top) / height) * 100}%`;
    el.style.width = `${(cell.width / width) * 100}%`;
    el.style.height = `${(cell.height / height) * 100}%`;
    if (cell.kind === "image") {
      el.src = cell.src;
      el.alt = "";
      box.append(el);
      if (cell.chart) charts.push(cell);
      return;
    }
    el.value = cell.text || "";
    el.rows = 1;
    el.spellcheck = false;
    el.setAttribute("aria-label", "Reading");
    el.addEventListener("input", () => {
      cell.text = el.value;
      if (phase === "accepted" || phase === "working") return;
      phase = hasInput() ? "ready" : "empty";
      render();
    });
    box.append(el);
  });
  if (!charts.length) return box;
  const block = document.createElement("div");
  block.className = "chart-block";
  block.append(box);
  charts.sort((a, b) => a.top - b.top || a.left - b.left);
  charts.forEach((cell) => {
    const chart = renderChart(cell.chart);
    if (chart) block.append(chart);
  });
  return block;
}

function scaleGrids() {
  partsEl.querySelectorAll(".grid").forEach((box) => {
    box.querySelectorAll("textarea").forEach((area) => {
      const cellH = area.getBoundingClientRect().height;
      if (!cellH) return;
      const size = Math.min(18, Math.max(8, cellH * 0.75));
      area.style.fontSize = `${size}px`;
      area.style.lineHeight = `${cellH}px`;
    });
  });
}

function showParts(list) {
  parts = list;
  partsEl.replaceChildren();
  let row = null;
  let band = null;
  list.forEach((part) => {
    if (part.kind === "grid") {
      closeBand(row, band);
      row = null;
      band = null;
      partsEl.append(renderGrid(part));
      return;
    }
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
    appendPicture(row, part);
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
  if (!partsEl.hidden) {
    partsEl.querySelectorAll("textarea").forEach((area) => {
      if (!area.closest(".grid")) fit(area, 1);
    });
    scaleGrids();
  }
});

function sheet() {
  render();
  if (!reading.hidden) fit(reading);
  if (!partsEl.hidden) {
    partsEl.querySelectorAll("textarea").forEach((area) => {
      if (!area.closest(".grid")) fit(area, 1);
    });
    scaleGrids();
  }
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
  const pictures = payload.parts && payload.parts.some((part) => part.kind === "image" || part.kind === "grid");
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
