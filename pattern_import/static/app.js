const FETCH_FAILED = "This address did not come back. Check it, or paste the pattern.";
const PARSE_WORKING = "Parsing the reading…";
const PARSE_DONE = "The reading is parsed.";
const PARSE_FAILED = "The reading did not parse.";
const MODEL_SILENT = "The model did not answer.";
const ACCEPT_LABEL = "Accept this input";
const RETRY_LABEL = "Try again";
const STAGE_LABELS = {
  bootstrap: "Starting…",
  metadata: "Naming the pattern…",
  pieces: "Finding pieces…",
  vocabulary: "Reading abbreviations…",
  sizes: "Reading sizes…",
  sections: "Splitting the pattern…",
  passes: "Building passes…",
  charts: "Reading charts…",
};

const tabs = [...document.querySelectorAll("[role='tab']")];
const urlPanel = document.getElementById("url-panel");
const filePanel = document.getElementById("file-panel");
const control = document.querySelector(".control");
const source = document.getElementById("source");
const readingWrap = document.getElementById("reading-wrap");
const notice = document.getElementById("notice");
const reading = document.getElementById("reading");
const partsEl = document.getElementById("parts");
const piecesEl = document.getElementById("pieces");
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
let parseMessage = "";

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
  if (frozen() || phase === "working") return;
  fit(reading);
  if (phase === "empty" || phase === "failed") {
    phase = reading.value.trim() ? "ready" : "empty";
    source.textContent = phase === "ready" ? "Pasted" : "";
  }
  render();
});

accept.addEventListener("click", () => {
  if (phase === "parsing" || phase === "parsed" || !hasInput()) return;
  const payload = acceptPayload();
  const mine = ++token;
  phase = "parsing";
  parseMessage = "";
  piecesEl.replaceChildren();
  render();
  fetch("/accept", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
    .then((response) => readAccept(response, mine))
    .catch(() => {
      if (mine !== token) return;
      phase = "parse-failed";
      parseMessage = MODEL_SILENT;
      render();
      accept.focus();
    });
});

async function readAccept(response, mine) {
  if (!response.ok || !response.body) {
    if (mine !== token) return;
    phase = "parse-failed";
    parseMessage = MODEL_SILENT;
    render();
    accept.focus();
    return;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) {
      if (mine !== token) return;
      const line = part.split("\n").find((row) => row.startsWith("data:"));
      if (!line) continue;
      let event;
      try {
        event = JSON.parse(line.slice(5).trim());
      } catch {
        continue;
      }
      if (event.type === "stage") {
        parseMessage = STAGE_LABELS[event.name] || PARSE_WORKING;
        render();
        continue;
      }
      if (event.type === "piece_ready") {
        continue;
      }
      if (event.type === "delta") {
        const chars = event.chars || 0;
        if (!parseMessage || parseMessage === PARSE_WORKING) {
          parseMessage = chars ? `${PARSE_WORKING} (${formatChars(chars)})` : PARSE_WORKING;
          render();
        }
        continue;
      }
      if (event.type === "error" || (event.type === "done" && !event.ok)) {
        phase = "parse-failed";
        parseMessage = event.message || PARSE_FAILED;
        render();
        accept.focus();
        return;
      }
      if (event.type === "done") {
        phase = "parsed";
        parseMessage = "";
        showPieces(event.sections ? event.sections.map(sectionLine) : event.pieces || []);
        render();
        piecesEl.scrollIntoView({ block: "nearest" });
        return;
      }
    }
  }
  if (mine !== token) return;
  phase = "parse-failed";
  parseMessage = MODEL_SILENT;
  render();
  accept.focus();
}

function formatChars(chars) {
  if (chars < 1000) return String(chars);
  return `${(chars / 1000).toFixed(chars < 10000 ? 1 : 0)}k`;
}
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
  row.replaceChildren();
  columns.forEach((column) => {
    const stack = document.createElement("div");
    stack.className = "stack";
    stack.style.flex = `${column.width} 1 0`;
    column.parts.forEach((part) => appendPicture(stack, part));
    row.append(stack);
  });
}

function renderChart(chart) {
  if (!chart || !chart.grid || !chart.grid.length || !chart.grid[0].length) return null;
  const rows = chart.grid.length;
  const cols = chart.grid[0].length;
  const box = document.createElement("div");
  box.className = "chart";
  box.style.gridTemplateColumns = `repeat(${cols}, minmax(0, 1fr))`;
  box.style.gridTemplateRows = `repeat(${rows}, minmax(0, 1fr))`;
  box.setAttribute("role", "img");
  box.setAttribute("aria-label", `Chart, ${rows} rows of ${cols}`);
  chart.grid.forEach((row) => {
    row.forEach((index) => {
      const square = document.createElement("span");
      const color = chart.colors && (chart.colors[index] || chart.colors[String(index)]);
      square.style.background = color || "transparent";
      box.append(square);
    });
  });
  return box;
}

function pngSize(src) {
  const marker = "base64,";
  const at = src ? src.indexOf(marker) : -1;
  if (at < 0 || !src.startsWith("data:image/png")) return null;
  let raw;
  try {
    raw = atob(src.slice(at + marker.length, at + marker.length + 48));
  } catch {
    return null;
  }
  if (raw.length < 24 || raw.slice(12, 16) !== "IHDR") return null;
  const u32 = (index) => (
    raw.charCodeAt(index) * 16777216
    + (raw.charCodeAt(index + 1) << 16)
    + (raw.charCodeAt(index + 2) << 8)
    + raw.charCodeAt(index + 3)
  ) >>> 0;
  return { width: u32(16), height: u32(20) };
}

function appendPicture(parent, part) {
  const chart = renderChart(part.chart);
  if (chart) {
    const size = pngSize(part.src);
    const width = (size && size.width) || part.width;
    const height = (size && size.height) || part.height;
    if (width && height) chart.style.aspectRatio = `${width} / ${height}`;
    if (!parent.classList.contains("stack") && width) {
      chart.style.width = `${width}px`;
      chart.style.maxWidth = "100%";
    }
    parent.append(chart);
    return;
  }
  const img = document.createElement("img");
  img.src = part.src;
  img.alt = "";
  parent.append(img);
}

function renderGrid(grid) {
  const box = document.createElement("div");
  box.className = "grid";
  const width = grid.width || 1;
  const height = grid.height || 1;
  box.style.aspectRatio = `${width} / ${height}`;
  (grid.cells || []).forEach((cell) => {
    const chart = cell.kind === "image" ? renderChart(cell.chart) : null;
    const el = chart || (cell.kind === "image" ? document.createElement("img") : document.createElement("textarea"));
    el.classList.add("cell");
    el.style.left = `${((cell.left - grid.left) / width) * 100}%`;
    el.style.top = `${((cell.top - grid.top) / height) * 100}%`;
    el.style.width = `${(cell.width / width) * 100}%`;
    el.style.height = `${(cell.height / height) * 100}%`;
    if (chart) {
      box.append(el);
      return;
    }
    if (cell.kind === "image") {
      el.src = cell.src;
      el.alt = "";
      box.append(el);
      return;
    }
    el.value = cell.text || "";
    el.rows = 1;
    el.spellcheck = false;
    el.setAttribute("aria-label", "Reading");
    el.addEventListener("input", () => {
      cell.text = el.value;
      if (frozen() || phase === "working") return;
      phase = hasInput() ? "ready" : "empty";
      render();
    });
    box.append(el);
  });
  return box;
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
        if (frozen() || phase === "working") return;
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

function frozen() {
  return phase === "parsing" || phase === "parsed" || phase === "parse-failed";
}

function acceptPayload() {
  return { reading: frozenReading(), charts: frozenCharts() };
}

function frozenReading() {
  if (!parts) return reading.value;
  return parts.map(partText).filter((text) => text.trim() !== "").join("\n\n");
}

function frozenCharts() {
  if (!parts) return [];
  const charts = [];
  parts.forEach((part) => {
    if (part.kind === "grid") {
      const labels = partText(part);
      (part.cells || []).forEach((cell) => {
        if (cell.kind === "image" && cell.chart && cell.chart.grid) {
          charts.push({
            grid: cell.chart.grid,
            colors: cell.chart.colors || {},
            labels,
          });
        }
      });
      return;
    }
    if (part.kind === "image" && part.chart && part.chart.grid) {
      charts.push({
        grid: part.chart.grid,
        colors: part.chart.colors || {},
        labels: "",
      });
    }
  });
  return charts;
}

function partText(part) {
  if (part.kind === "text") return part.text || "";
  if (part.kind !== "grid") return "";
  return (part.cells || [])
    .filter((cell) => cell.kind === "text")
    .map((cell) => cell.text || "")
    .filter((text) => text.trim() !== "")
    .join("\n\n");
}

function sectionLine(text) {
  const line = String(text).trim().split("\n")[0];
  return { name: line, parsed: true, sizes: [] };
}

function showPieces(list) {
  piecesEl.replaceChildren();
  list.forEach((piece) => {
    const block = document.createElement("p");
    block.append(piece.name);
    if (piece.parsed && (piece.sizes || []).length) {
      block.append(document.createElement("br"));
      block.append(piece.sizes.join(", "));
    } else if (!piece.parsed) {
      block.append(document.createElement("br"));
      const mark = document.createElement("span");
      mark.className = "unparsed";
      mark.textContent = "Unparsed";
      block.append(mark);
    }
    piecesEl.append(block);
  });
}

function reset() {
  token += 1;
  tab = "paste";
  phase = "empty";
  parts = null;
  parseMessage = "";
  partsEl.replaceChildren();
  piecesEl.replaceChildren();
  source.textContent = "";
  notice.textContent = "";
  settled.textContent = "";
  reading.value = "";
  urlInput.value = "";
  fileInput.value = "";
  fileLabel.textContent = "Choose an HTML, PDF, or TXT file";
  sheet();
  reading.focus();
}

function settledText() {
  if (phase === "parsing") return parseMessage || PARSE_WORKING;
  if (phase === "parsed") return PARSE_DONE;
  if (phase === "parse-failed") return parseMessage || PARSE_FAILED;
  return "";
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

  const fetchNotice = phase === "working" || phase === "failed";
  notice.hidden = !fetchNotice;
  const split = parts !== null;
  reading.hidden = split || (fetchNotice && tab !== "paste");
  if (phase === "working") reading.hidden = true;
  partsEl.hidden = !split || phase === "working" || (fetchNotice && tab !== "paste");
  piecesEl.hidden = phase !== "parsed";
  reading.readOnly = frozen();
  partsEl.querySelectorAll("textarea").forEach((area) => {
    area.readOnly = frozen();
  });

  const status = settledText();
  settled.textContent = status;
  settled.hidden = status === "";
  accept.textContent = phase === "parse-failed" ? RETRY_LABEL : ACCEPT_LABEL;
  accept.hidden = phase === "parsing" || phase === "parsed";
  discard.hidden = frozen();
  another.hidden = phase !== "parsed" && phase !== "parse-failed";
  accept.disabled = phase === "parsing" || (phase !== "parse-failed" && (phase !== "ready" || !hasInput()));
  discard.disabled = phase === "empty";
}

render();
