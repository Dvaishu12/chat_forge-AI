const fileInput = document.querySelector("#file-input");
const uploadZone = document.querySelector("#upload-zone");
const uploadPrompt = document.querySelector("#upload-prompt");
const previewWrap = document.querySelector("#preview-wrap");
const imagePreview = document.querySelector("#image-preview");
const textOutput = document.querySelector("#text-output");
const questionInput = document.querySelector("#question-input");
const sendButton = document.querySelector(".send-button");
const conversation = document.querySelector("#conversation");
const conversationEmpty = document.querySelector("#conversation-empty");
const toast = document.querySelector("#toast");
let activeImageId = null;
let toastTimer;

function refreshIcons() {
  if (window.lucide) window.lucide.createIcons();
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("visible"), 4200);
}

function setPipeline(state, completed = 0) {
  document.querySelectorAll(".pipeline-step").forEach((step, index) => {
    step.classList.toggle("done", index < completed);
    step.classList.toggle("current", state === "working" && index === completed);
  });
  const badge = document.querySelector("#pipeline-state");
  const labels = { ready: "READY", working: "PROCESSING", complete: "INDEXED", error: "RETRY" };
  badge.className = `pipeline-state ${state}`;
  badge.innerHTML = `<span></span> ${labels[state] || "READY"}`;
}

function setComposerEnabled(enabled) {
  questionInput.disabled = !enabled;
  sendButton.disabled = !enabled || !questionInput.value.trim();
  document.querySelector("#composer-hint").innerHTML = enabled
    ? '<i data-lucide="corner-down-left"></i> Answers use this image as context'
    : '<i data-lucide="paperclip"></i> Upload an image to unlock questions';
  document.querySelectorAll(".suggestion").forEach((button) => { button.disabled = !enabled; });
  refreshIcons();
}

function formatBytes(bytes) {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function processImage(file) {
  if (!file) return;
  if (!file.type.startsWith("image/")) return showToast("Choose a PNG, JPG, WEBP, or TIFF image.");
  if (file.size > 12 * 1024 * 1024) return showToast("This image is over the 12 MB limit.");

  activeImageId = null;
  setComposerEnabled(false);
  conversation.innerHTML = "";
  conversation.classList.add("hidden");
  conversationEmpty.classList.remove("hidden");
  uploadPrompt.classList.add("hidden");
  previewWrap.classList.remove("hidden");
  if (imagePreview.dataset.objectUrl) URL.revokeObjectURL(imagePreview.dataset.objectUrl);
  imagePreview.dataset.objectUrl = URL.createObjectURL(file);
  imagePreview.src = imagePreview.dataset.objectUrl;
  document.querySelector("#file-name").textContent = `${file.name} · ${formatBytes(file.size)}`;
  document.querySelector("#source-meta").textContent = "PREPARING IMAGE";
  document.querySelector("#char-count").textContent = "READING IMAGE";
  textOutput.classList.add("empty-state");
  textOutput.innerHTML = '<div class="empty-text-icon"><i data-lucide="loader-circle"></i></div><p>Reading your image…</p><span>Enhancing and extracting text</span>';
  setPipeline("working", 0);
  refreshIcons();

  const formData = new FormData();
  formData.append("file", file);
  try {
    const response = await fetch("/api/process", { method: "POST", body: formData });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Could not process this image.");
    activeImageId = result.image_id;
    textOutput.classList.remove("empty-state");
    textOutput.textContent = result.text;
    document.querySelector("#char-count").textContent = `${result.character_count.toLocaleString()} CHARACTERS`;
    document.querySelector("#source-meta").textContent = `${result.chunk_count} CHUNKS INDEXED`;
    setPipeline("complete", 4);
    setComposerEnabled(true);
    document.querySelector("#composer-hint").innerHTML = `<i data-lucide="layers-2"></i> ${result.chunk_count} searchable text chunks`;
    refreshIcons();
  } catch (error) {
    setPipeline("error", 0);
    document.querySelector("#source-meta").textContent = "PROCESSING FAILED";
    textOutput.classList.add("empty-state");
    textOutput.innerHTML = '<div class="empty-text-icon"><i data-lucide="circle-alert"></i></div><p>Could not read this image.</p><span>Check the server setup and try again</span>';
    refreshIcons();
    showToast(error.message);
  }
}

function addMessage(role, content, sources = []) {
  const message = document.createElement("div");
  message.className = `message ${role}`;
  const label = document.createElement("div");
  label.className = "message-label";
  if (role === "assistant") label.innerHTML = '<i data-lucide="sparkles"></i> GROUNDED ANSWER';
  else label.textContent = "YOUR QUESTION";
  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  bubble.textContent = content;
  message.append(label, bubble);
  if (sources.length) {
    const sourceList = document.createElement("div");
    sourceList.className = "source-list";
    sources.forEach((source) => {
      const item = document.createElement("div");
      item.className = "source-item";
      item.textContent = source;
      sourceList.append(item);
    });
    message.append(sourceList);
  }
  conversation.append(message);
  conversation.scrollTop = conversation.scrollHeight;
  refreshIcons();
}

async function askQuestion(question) {
  if (!activeImageId || !question.trim()) return;
  conversationEmpty.classList.add("hidden");
  conversation.classList.remove("hidden");
  addMessage("user", question.trim());
  questionInput.value = "";
  questionInput.style.height = "auto";
  sendButton.disabled = true;
  const loadingMessage = document.createElement("div");
  loadingMessage.className = "message assistant";
  loadingMessage.innerHTML = '<div class="message-label"><i data-lucide="sparkles"></i> SEARCHING YOUR IMAGE</div><div class="loading-dots"><span></span><span></span><span></span></div>';
  conversation.append(loadingMessage);
  conversation.scrollTop = conversation.scrollHeight;
  refreshIcons();

  try {
    const response = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image_id: activeImageId, question: question.trim() }),
    });

    const responseText = await response.text();
    let result;
    try {
      result = responseText ? JSON.parse(responseText) : {};
    } catch {
      throw new Error(responseText || "The answer could not be generated.");
    }

    if (!response.ok) throw new Error(result.detail || "The answer could not be generated.");
    loadingMessage.remove();
    addMessage("assistant", result.answer, result.sources);
  } catch (error) {
    loadingMessage.remove();
    addMessage("assistant", error.message);
  }
}

fileInput.addEventListener("change", () => processImage(fileInput.files[0]));
document.querySelector("#browse-button").addEventListener("click", (event) => { event.stopPropagation(); fileInput.click(); });
document.querySelector("#new-image-button").addEventListener("click", () => fileInput.click());
uploadZone.addEventListener("click", (event) => { if (!event.target.closest("button")) fileInput.click(); });
uploadZone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") { event.preventDefault(); fileInput.click(); }
});
uploadZone.addEventListener("dragover", (event) => { event.preventDefault(); uploadZone.classList.add("drag-over"); });
uploadZone.addEventListener("dragleave", () => uploadZone.classList.remove("drag-over"));
uploadZone.addEventListener("drop", (event) => { event.preventDefault(); uploadZone.classList.remove("drag-over"); processImage(event.dataTransfer.files[0]); });
questionInput.addEventListener("input", () => {
  questionInput.style.height = "auto";
  questionInput.style.height = `${Math.min(questionInput.scrollHeight, 95)}px`;
  sendButton.disabled = !activeImageId || !questionInput.value.trim();
});
document.querySelector("#question-form").addEventListener("submit", (event) => { event.preventDefault(); askQuestion(questionInput.value); });
document.querySelectorAll(".suggestion").forEach((button) => button.addEventListener("click", () => askQuestion(button.dataset.question)));

fetch("/api/health")
  .then((response) => response.json())
  .then((health) => {
    document.querySelector("#connection-dot").classList.add("online");
    document.querySelector("#connection-text").textContent = health.groq_configured ? "OCR + AI connected" : "OCR ready · AI key needed";
  })
  .catch(() => {
    document.querySelector("#connection-dot").classList.add("offline");
    document.querySelector("#connection-text").textContent = "Server not connected";
  });

refreshIcons();