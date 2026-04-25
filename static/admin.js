const tokenInput = document.getElementById("tokenInput");
const loadButton = document.getElementById("loadButton");
const saveButton = document.getElementById("saveButton");
const configEditor = document.getElementById("configEditor");
const statusText = document.getElementById("statusText");
const TOKEN_KEY = "mitex_admin_token";

tokenInput.value = localStorage.getItem(TOKEN_KEY) || "";

function setStatus(message, tone = "neutral") {
  statusText.textContent = message;
  statusText.dataset.tone = tone;
}

function getToken() {
  const token = tokenInput.value.trim();
  if (token) {
    localStorage.setItem(TOKEN_KEY, token);
  }
  return token;
}

async function loadConfig() {
  const token = getToken();
  if (!token) {
    setStatus("Admin token is required.", "error");
    return;
  }

  setStatus("Loading knowledge base...");
  const response = await fetch("/admin/config", {
    headers: { "X-Admin-Token": token },
  });
  const payload = await response.json();

  if (!response.ok) {
    setStatus(payload.error || "Unable to load config.", "error");
    return;
  }

  configEditor.value = JSON.stringify(payload, null, 2);
  setStatus("Knowledge base loaded.", "success");
}

async function saveConfig() {
  const token = getToken();
  if (!token) {
    setStatus("Admin token is required.", "error");
    return;
  }

  let parsed;
  try {
    parsed = JSON.parse(configEditor.value);
  } catch (error) {
    setStatus(`Invalid JSON: ${error.message}`, "error");
    return;
  }

  setStatus("Saving and reloading chatbot knowledge...");
  const response = await fetch("/admin/config", {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      "X-Admin-Token": token,
    },
    body: JSON.stringify(parsed),
  });
  const payload = await response.json();

  if (!response.ok) {
    setStatus(payload.error || "Unable to save config.", "error");
    return;
  }

  configEditor.value = JSON.stringify(parsed, null, 2);
  setStatus(payload.message || "Saved.", "success");
}

loadButton.addEventListener("click", loadConfig);
saveButton.addEventListener("click", saveConfig);
