const form = document.getElementById("jobForm");
const tokenInput = document.getElementById("tokenInput");
const statusBox = document.getElementById("statusBox");
const downloadLink = document.getElementById("downloadLink");
const TOKEN_KEY = "restaurant_lead_agent_token";

tokenInput.value = localStorage.getItem(TOKEN_KEY) || "";

function setStatus(message, tone = "neutral") {
  statusBox.textContent = message;
  statusBox.dataset.tone = tone;
}

async function pollJob(jobId, token) {
  const response = await fetch(`/jobs/${jobId}`, {
    headers: token ? { "X-Agent-Token": token } : {},
  });
  const payload = await response.json();

  if (!response.ok) {
    setStatus(payload.error || "Unable to read job.", "error");
    return;
  }

  setStatus(payload.message || payload.status, payload.status === "failed" ? "error" : "neutral");

  if (payload.status === "completed") {
    downloadLink.href = token ? `${payload.download_url}?token=${encodeURIComponent(token)}` : payload.download_url;
    downloadLink.hidden = false;
    setStatus(payload.message, "success");
    return;
  }

  if (payload.status !== "failed") {
    setTimeout(() => pollJob(jobId, token), 1800);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  downloadLink.hidden = true;
  const token = tokenInput.value.trim();
  if (token) {
    localStorage.setItem(TOKEN_KEY, token);
  }

  setStatus("Starting enrichment agent...");
  const response = await fetch("/jobs", {
    method: "POST",
    headers: token ? { "X-Agent-Token": token } : {},
    body: new FormData(form),
  });
  const payload = await response.json();

  if (!response.ok) {
    setStatus(payload.error || "Unable to start job.", "error");
    return;
  }

  pollJob(payload.job_id, token);
});
