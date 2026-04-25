const chatLog = document.getElementById("chatLog");
const chatForm = document.getElementById("chatForm");
const messageInput = document.getElementById("messageInput");
const sendButton = document.getElementById("sendButton");
const voiceButton = document.getElementById("voiceButton");
const providerChip = document.getElementById("providerChip");
const latencyChip = document.getElementById("latencyChip");
const CLIENT_ID_STORAGE_KEY = "mitex_client_id";
const SpeechRecognition =
  window.SpeechRecognition || window.webkitSpeechRecognition || null;

let recognition = null;
let isListening = false;

function getOrCreateClientId() {
  const existing = localStorage.getItem(CLIENT_ID_STORAGE_KEY);
  if (existing) {
    return existing;
  }

  const generated =
    typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;

  localStorage.setItem(CLIENT_ID_STORAGE_KEY, generated);
  return generated;
}

const clientId = getOrCreateClientId();

function appendMessage(role, text, source = "") {
  const wrapper = document.createElement("div");
  wrapper.className = `msg ${role}`;

  const body = document.createElement("div");
  body.textContent = text;
  wrapper.appendChild(body);

  if (source) {
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = `source: ${source}`;
    wrapper.appendChild(meta);
  }

  chatLog.appendChild(wrapper);
  chatLog.scrollTop = chatLog.scrollHeight;
}

async function refreshStatus() {
  try {
    const response = await fetch("/status");
    const payload = await response.json();
    providerChip.textContent = `Provider: ${payload.provider}`;
    latencyChip.textContent = `Avg latency: ${payload.metrics.avg_latency_ms} ms`;
  } catch (_error) {
    providerChip.textContent = "Provider: unavailable";
  }
}

async function sendMessage(message) {
  appendMessage("user", message);
  sendButton.disabled = true;
  voiceButton.disabled = true;

  try {
    const response = await fetch("/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Client-Id": clientId,
      },
      body: JSON.stringify({ message }),
    });

    const payload = await response.json();
    appendMessage("bot", payload.reply, payload.source);
    await refreshStatus();
  } catch (_error) {
    appendMessage("bot", "Request failed. Please try again.", "network_error");
  } finally {
    sendButton.disabled = false;
    voiceButton.disabled = !SpeechRecognition;
  }
}

function setVoiceListening(nextState) {
  isListening = nextState;
  voiceButton.classList.toggle("is-listening", isListening);
  voiceButton.setAttribute(
    "aria-label",
    isListening ? "Stop voice input" : "Use voice input"
  );
  voiceButton.title = isListening ? "Stop voice input" : "Use voice input";
}

function appendTranscript(transcript) {
  const currentValue = messageInput.value.trim();
  messageInput.value = currentValue ? `${currentValue} ${transcript}` : transcript;
  messageInput.focus();
}

function setupVoiceInput() {
  if (!SpeechRecognition) {
    voiceButton.disabled = true;
    voiceButton.title = "Voice input is not supported in this browser";
    return;
  }

  recognition = new SpeechRecognition();
  recognition.lang = "en-US";
  recognition.interimResults = true;
  recognition.continuous = false;

  recognition.addEventListener("start", () => {
    setVoiceListening(true);
  });

  recognition.addEventListener("end", () => {
    setVoiceListening(false);
  });

  recognition.addEventListener("error", () => {
    setVoiceListening(false);
  });

  recognition.addEventListener("result", (event) => {
    let finalTranscript = "";

    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const result = event.results[index];
      if (result.isFinal) {
        finalTranscript += result[0].transcript;
      }
    }

    if (finalTranscript.trim()) {
      appendTranscript(finalTranscript.trim());
    }
  });

  voiceButton.addEventListener("click", () => {
    if (isListening) {
      recognition.stop();
      return;
    }

    recognition.start();
  });
}

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = messageInput.value.trim();
  if (!message) {
    return;
  }

  messageInput.value = "";
  await sendMessage(message);
});

document.querySelectorAll(".mission").forEach((button) => {
  button.addEventListener("click", async () => {
    const prompt = button.dataset.prompt;
    if (prompt) {
      await sendMessage(prompt);
    }
  });
});

setupVoiceInput();

appendMessage(
  "bot",
  "Hi, I am the Little Red Wasp assistant. I can help with menus, hours, reservations, brunch, happy hour, events, and contact details.",
  "system"
);

refreshStatus();
