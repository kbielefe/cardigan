const NONE = "None on this page. A list in the pattern would sit here. Cardigan does not add one.";
const FETCH_FAILED = "This address did not come back. Check it, or paste the pattern.";

const tabs = [...document.querySelectorAll("[role='tab']")];
const urlPanel = document.getElementById("url-panel");
const filePanel = document.getElementById("file-panel");
const control = document.querySelector(".control");
const source = document.getElementById("source");
const none = document.getElementById("abbr-none");
const list = document.getElementById("abbr-list");
const readingWrap = document.getElementById("reading-wrap");
const notice = document.getElementById("notice");
const reading = document.getElementById("reading");
const count = document.getElementById("count");
const discard = document.getElementById("discard");
const another = document.getElementById("another");
const settled = document.getElementById("settled");
const urlInput = document.getElementById("url");
const fileInput = document.getElementById("file");
const fileLabel = document.getElementById("file-label");

let tab = "paste";
let phase = "empty";
let hasList = false;
let splitDone = false;
let token = 0;

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
  if (phase === "counted" || phase === "working") return;
  fit(reading);
  if (phase === "empty" || phase === "failed") {
    phase = reading.value.trim() ? "ready" : "empty";
    source.textContent = phase === "ready" ? "Pasted" : "";
    if (phase === "empty") splitDone = false;
  }
  render();
});

reading.addEventListener("paste", () => {
  const fresh = reading.value.trim() === "" || phase === "empty" || phase === "failed";
  if (!fresh) return;
  splitDone = false;
  setTimeout(() => {
    if (!splitDone) landPaste();
  }, 0);
});

reading.addEventListener("blur", () => {
  if (!splitDone && phase === "ready" && tab === "paste") landPaste();
});

count.addEventListener("click", () => {
  if (!wordsIn()) return;
  phase = "counted";
  render();
});

discard.addEventListener("click", reset);
another.addEventListener("click", reset);

function wordsIn() {
  return reading.value.trim() !== "" || (hasList && list.value.trim() !== "");
}

function fit(area) {
  const lines = area.value ? area.value.split("\n").length : 1;
  area.rows = Math.max(area === reading ? 8 : 2, lines);
  area.style.height = "auto";
  const floor = area.getBoundingClientRect().height;
  area.style.height = `${Math.max(floor, area.scrollHeight)}px`;
  if (area.scrollHeight > area.clientHeight) {
    area.style.height = `${area.scrollHeight}px`;
  }
}

window.addEventListener("resize", () => {
  if (!reading.hidden) fit(reading);
  if (!list.hidden) fit(list);
});

function showList(value) {
  if (value == null) {
    hasList = false;
    list.value = "";
  } else {
    hasList = true;
    list.value = value;
  }
}

function sheet() {
  render();
  if (!reading.hidden) fit(reading);
  if (!list.hidden) fit(list);
}

async function landPaste() {
  const text = reading.value;
  if (!text.trim()) return;
  const mine = ++token;
  let payload;
  try {
    const response = await fetch("/split", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    payload = await response.json();
  } catch {
    return;
  }
  if (mine !== token || reading.value !== text || !payload.ok) return;
  splitDone = true;
  reading.value = payload.reading;
  showList(payload.abbreviations);
  phase = wordsIn() ? "ready" : "empty";
  if (phase === "ready") source.textContent = "Pasted";
  sheet();
}

async function begin(run) {
  const mine = ++token;
  phase = "working";
  splitDone = true;
  hasList = false;
  list.value = "";
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
  reading.value = payload.reading || "";
  showList(payload.abbreviations);
  sheet();
}

function reset() {
  token += 1;
  tab = "paste";
  phase = "empty";
  hasList = false;
  splitDone = false;
  source.textContent = "";
  notice.textContent = "";
  reading.value = "";
  list.value = "";
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
  none.hidden = hasList;
  none.textContent = NONE;
  list.hidden = !hasList;
  list.readOnly = phase === "counted";

  const showNotice = phase === "working" || phase === "failed";
  notice.hidden = !showNotice;
  reading.hidden = showNotice && tab !== "paste";
  if (phase === "working") reading.hidden = true;
  reading.readOnly = phase === "counted";

  const counted = phase === "counted";
  settled.hidden = !counted;
  count.hidden = counted;
  discard.hidden = counted;
  another.hidden = !counted;
  count.disabled = phase !== "ready" || !wordsIn();
  discard.disabled = phase === "empty";
}

render();
