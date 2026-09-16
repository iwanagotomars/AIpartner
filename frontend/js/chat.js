const BUSY_POLL_MS = 200;
const IDLE_POLL_MS = 2000;
const IDLE_CONFIRM_COUNT = 5;
const DISPLAY_GAP_MS = 300;
const HISTORY_PAGE_SIZE = 10;
const MAX_VISIBLE_HISTORY_TURNS = 100;
const HISTORY_TIME_GAP_SECONDS = 20 * 60;
const GAL_WELCOME_SPEAKER = "系统提示";
const GAL_WELCOME_TEXT =
  "在下方对话框中输入你想说的话来开始话题。鼠标移动到页面顶部来修改设置。";

const currentCharacter = decodeURIComponent(
  window.location.pathname.split("/").filter(Boolean).at(-1),
);
const encodedCharacter = encodeURIComponent(currentCharacter);
const pageParams = new URLSearchParams(window.location.search);
const runtimeId = pageParams.get("runtime_id");
let displayCharacter = pageParams.get("display_name") || currentCharacter;

document.title = displayCharacter;
const characterProfileUrl =
  `/api/characters/${encodedCharacter}/profile`;
let currentUserProfileUrl =
  `/api/characters/${encodedCharacter}/user-profile`;

const inputBox = document.getElementById("userInput");
const sendButton = document.getElementById("sendButton");
const closeCharacterButton = document.getElementById("closeCharacterButton");
const galModeButton = document.getElementById("galModeButton");
const textModeButton = document.getElementById("textModeButton");
const assetSelectButton = document.getElementById("assetSelectButton");
const assetFileInput = document.getElementById("assetFileInput");
const portraitLayoutButton = document.getElementById("portraitLayoutButton");
const uiStatus = document.getElementById("uiStatus");
const themePicker = document.getElementById("themePicker");
const portrait = document.getElementById("portrait");
const audio = document.getElementById("audio");
const voiceStatus = document.getElementById("voiceStatus");
const historyList = document.getElementById("historyList");
const historyTurnsElement = document.getElementById("historyTurns");
const historyTopStatus = document.getElementById("historyTopStatus");
const loadMoreHistoryButton = document.getElementById(
  "loadMoreHistoryButton",
);
const galView = window.createGalChatView({
  topbarArea: document.getElementById("topbarArea"),
  historyOverlay: document.getElementById("historyOverlay"),
  historyList,
  openHistoryButton: document.getElementById("openHistoryButton"),
  closeHistoryButton: document.getElementById("closeHistoryButton"),
  dialogueSpeaker: document.getElementById("galDialogueSpeaker"),
  dialogueText: document.getElementById("galDialogueText"),
});
const themeController = window.createChatThemeController({
  character: encodedCharacter,
  runtimeId,
  picker: themePicker,
  optionButtons: Array.from(
    themePicker.querySelectorAll("[data-chat-theme]"),
  ),
  showError: showUiError,
});
const portraitLayoutController = window.createPortraitLayoutController({
  character: encodedCharacter,
  runtimeId,
  trigger: portraitLayoutButton,
  panel: document.getElementById("portraitLayoutPanel"),
  scaleValue: document.getElementById("portraitScaleValue"),
  status: document.getElementById("portraitLayoutStatus"),
  resetButton: document.getElementById("portraitLayoutReset"),
  cancelButton: document.getElementById("portraitLayoutCancel"),
  saveButton: document.getElementById("portraitLayoutSave"),
});

let displayEnabled = true;
let isAudioUnlocked = false;
let displayPlaying = false;
let displayFetchPending = false;
let readyDisplayId = null;
let readyHistoryId = null;
let historyFetchPending = false;

const historyTurns = new Map();
const renderedHistoryEventIds = new Set();
let historyBeforeTurnId = null;
let historyHasMore = false;
let historyFilePath = "";
let historyLoading = false;
let historyLoadError = "";

// busy 使用 200ms 轮询并禁止输入；idle 使用 1s 轮询并允许输入。
let polling_status = "busy";
let consecutiveIdleChecks = 0;
let pollRequestPending = false;
let pollAgainImmediately = false;
let pollTimer = null;

let closingCharacter = false;
let conversationBlocked = false;
let pendingAssetType = null;
let assetUploadPending = false;
let uiStatusTimer = null;


// 文件对象和预览 URL 属于草稿；只有后端确认成功才清空。
const attachmentButton = document.getElementById("attachmentButton");
const attachmentMenu = document.getElementById("attachmentMenu");
const addImageButton = document.getElementById("addImageButton");
const chatImageInput = document.getElementById("chatImageInput");
const attachmentPanel = document.getElementById("attachmentPanel");
const imagePreviews = document.getElementById("imagePreviews");
const imageCount = document.getElementById("imageCount");
const imagePreviewToggle = document.getElementById("imagePreviewToggle");
let imagePreviewCollapsed = false;

// 只折叠展示，不改变附件草稿；失败恢复时仍保持用户选择的展开状态。
function updateImagePreviewState() {
  imagePreviews.hidden = imagePreviewCollapsed;
  imageCount.hidden = imagePreviewCollapsed;
  attachmentPanel.classList.toggle("is-collapsed", imagePreviewCollapsed);
  imagePreviewToggle.textContent = imagePreviewCollapsed
    ? `已选 ${pendingImages.length} 张图片 ▲` : "▼";
  imagePreviewToggle.setAttribute("aria-expanded", String(!imagePreviewCollapsed));
  imagePreviewToggle.setAttribute("aria-label", imagePreviewCollapsed ? "展开图片预览" : "收起图片预览");
}
imagePreviewToggle.addEventListener("click", () => {
  imagePreviewCollapsed = !imagePreviewCollapsed;
  updateImagePreviewState();
});
let pendingImages = [];
let sendInFlight = false;
let visionEnabled = false;
let maxChatImages = 3;
let maxImageBytes = 10 * 1024 * 1024;

function clearImageDraft() {
  pendingImages.forEach(({ preview }) => URL.revokeObjectURL(preview));
  pendingImages = [];
  imagePreviewCollapsed = false;
  renderImageDraft();
}

function renderImageDraft() {
  imagePreviews.replaceChildren();
  pendingImages.forEach(({ preview }, index) => {
    const card = document.createElement("div");
    card.className = "image-preview";
    const img = document.createElement("img");
    img.src = preview;
    img.alt = `待发送图片${index + 1}`;
    const label = document.createElement("span");
    label.textContent = `图片${index + 1}`;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.setAttribute("aria-label", `删除图片${index + 1}`);
    remove.addEventListener("click", () => {
      if (sendButton.disabled) return;
      URL.revokeObjectURL(pendingImages[index].preview);
      pendingImages.splice(index, 1);
      renderImageDraft();
    });
    card.append(img, label, remove);
    imagePreviews.appendChild(card);
  });
  attachmentPanel.hidden = pendingImages.length === 0;
  imageCount.textContent = `已选 ${pendingImages.length}/${maxChatImages} 张图片`;
  if (!pendingImages.length) imagePreviewCollapsed = false;
  updateImagePreviewState();
  applyControlState();
}

function fileDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("无法读取图片，请重新选择。"));
    reader.onabort = () => reject(new Error("图片读取已取消。"));
    reader.readAsDataURL(file);
  });
}

attachmentButton.addEventListener("click", () => {
  attachmentMenu.hidden = !attachmentMenu.hidden;
  attachmentButton.setAttribute("aria-expanded", String(!attachmentMenu.hidden));
});
document.addEventListener("click", (event) => {
  if (!event.target.closest(".attachment-actions")) {
    attachmentMenu.hidden = true;
    attachmentButton.setAttribute("aria-expanded", "false");
  }
});
addImageButton.addEventListener("click", () => {
  if (!visionEnabled || pendingImages.length >= maxChatImages || sendButton.disabled) return;
  attachmentMenu.hidden = true;
  attachmentButton.setAttribute("aria-expanded", "false");
  chatImageInput.click();
});
chatImageInput.addEventListener("change", () => {
  const files = Array.from(chatImageInput.files || []);
  chatImageInput.value = ""; // 允许移除后重新选择同一文件。
  if (!files.length || sendButton.disabled || !visionEnabled) return;
  if (files.length + pendingImages.length > maxChatImages) {
    showUiError(`最多添加${maxChatImages}张图片，还可添加${maxChatImages - pendingImages.length}张。`);
    return;
  }
  if (files.some((file) => !/\.(jpe?g|png)$/i.test(file.name) ||
      !["image/jpeg", "image/png"].includes(file.type) || file.size > maxImageBytes)) {
    showUiError("请选择 JPG、JPEG 或 PNG 图片，单张不超过10 MiB。");
    return;
  }
  imagePreviewCollapsed = false; // 新添加图片时展开，便于核对本次选择。
  pendingImages.push(...files.map((file) => ({ file, preview: URL.createObjectURL(file) })));
  renderImageDraft();
});
window.addEventListener("pagehide", () => {
  pendingImages.forEach(({ preview }) => URL.revokeObjectURL(preview));
});

function setBackgroundVariable(name, url) {
  document.body.style.setProperty(name, url ? `url("${url}")` : "none");
}

function applyFrontendAssets(data) {
  if (data.user_profile_url) {
    currentUserProfileUrl = data.user_profile_url;
  }
  setBackgroundVariable(
    "--gal-background-image",
    data.background_image_gal_url,
  );
  const opacity = Number(data.background_overlay_opacity);
  if (Number.isFinite(opacity)) {
    document.body.style.setProperty(
      "--background-overlay-opacity",
      String(Math.min(1, Math.max(0, opacity))),
    );
  }
}

async function loadFrontendAssets() {
  try {
    const response = await fetch(
      `/api/characters/${encodedCharacter}/frontend-assets`,
      { cache: "no-store" },
    );
    const data = await response.json();
    if (response.ok) applyFrontendAssets(data);
  } catch (error) {
    console.warn("读取前端图片失败，将使用页面默认样式。", error);
  }
}

function showGalWelcome(defaultPortraitUrl) {
  galView.showDialogue(GAL_WELCOME_SPEAKER, GAL_WELCOME_TEXT);
  if (defaultPortraitUrl) {
    portrait.src = defaultPortraitUrl;
    portrait.hidden = false;
  }
}

async function loadDisplayBootstrap() {
  if (!runtimeId) return;
  try {
    const response = await fetch(
      `/api/characters/${encodedCharacter}/display/bootstrap?runtime_id=` +
        encodeURIComponent(runtimeId),
      { cache: "no-store" },
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(getErrorMessage(data, "无法读取旮旯模式初始化信息。"));
    }

    visionEnabled = data.vision_enabled === true;
    maxChatImages = data.max_chat_images || 3;
    maxImageBytes = data.max_image_bytes || 10 * 1024 * 1024;
    document.getElementById("visionHint").textContent = data.vision_unavailable_reason || `最多${maxChatImages}张，单张不超过10 MiB`;
    updateChatMode(Boolean(data.display_enabled));
    applyControlState();
    if (data.display_enabled) showGalWelcome(data.default_portrait_url);
  } catch (error) {
    // 初始化展示失败不应阻断历史记录、状态轮询或正常对话。
    console.warn("读取旮旯模式初始化信息失败。", error);
  }
}

function showUiError(message) {
  clearTimeout(uiStatusTimer);
  uiStatus.textContent = message;
  uiStatusTimer = setTimeout(() => {
    uiStatus.textContent = "";
  }, 5000);
}

function chooseFrontendAsset(assetType) {
  if (assetUploadPending) return;
  pendingAssetType = assetType;
  assetFileInput.value = "";
  assetFileInput.click();
}

function applyUploadedAsset(assetType, url) {
  if (assetType === "user_profile") {
    currentUserProfileUrl = url;
    historyList.querySelectorAll(".history-event--user .history-avatar")
      .forEach((avatar) => {
        avatar.hidden = false;
        avatar.src = url;
      });
  } else if (assetType === "background_image_gal") {
    setBackgroundVariable("--gal-background-image", url);
  }
}

async function uploadFrontendAsset(file) {
  const assetType = pendingAssetType;
  pendingAssetType = null;
  if (!file || !assetType || assetUploadPending) return;

  assetUploadPending = true;
  assetSelectButton.disabled = true;
  try {
    const response = await fetch(
      `/api/characters/${encodedCharacter}/frontend-assets/` +
        `${encodeURIComponent(assetType)}?runtime_id=` +
        encodeURIComponent(runtimeId),
      {
        method: "PUT",
        headers: { "Content-Type": file.type || "application/octet-stream" },
        body: file,
      },
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(getErrorMessage(data, "图片保存失败。"));
    }
    applyUploadedAsset(data.asset_type, data.url);
    clearTimeout(uiStatusTimer);
    uiStatus.textContent = "";
  } catch (error) {
    showUiError("图片保存失败：" + error.message);
  } finally {
    assetUploadPending = false;
    assetSelectButton.disabled = false;
  }
}

async function loadTrueCharacterName() {
  try {
    const response = await fetch("/api/characters", { cache: "no-store" });
    const data = await response.json();
    if (!response.ok) return;
    const character = data.characters?.find(
      (item) => item.name === currentCharacter,
    );
    if (character?.display_name) {
      displayCharacter = character.display_name;
      document.title = displayCharacter;
    }
  } catch (error) {
    console.warn("读取角色真名失败，将使用角色目录名。", error);
  }
}

async function unlockAudio() {
  if (isAudioUnlocked) return;
  const silentAudio = new Audio(
    "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=",
  );
  silentAudio.muted = true;
  try {
    await silentAudio.play();
    isAudioUnlocked = true;
  } catch (error) {
    console.warn("音频自动播放解锁失败", error);
  }
}

function applyControlState() {
  const disabled = (
    sendInFlight || polling_status === "busy" ||
    closingCharacter ||
    conversationBlocked
  );
  inputBox.disabled = disabled;
  sendButton.disabled = disabled;
  attachmentButton.disabled = disabled;
  addImageButton.disabled = disabled || !visionEnabled || pendingImages.length >= maxChatImages;
  chatImageInput.disabled = disabled || !visionEnabled;
  imagePreviews.querySelectorAll("button").forEach((button) => { button.disabled = disabled; });
  closeCharacterButton.disabled = disabled;
  galModeButton.disabled = disabled;
  textModeButton.disabled = disabled;
  portraitLayoutController.setAvailable(displayEnabled && !disabled);
}

function setPollingStatus(status) {
  if (status !== "busy" && status !== "idle") return;
  polling_status = status;
  document.body.dataset.pollingStatus = status;
  applyControlState();
}

function updateChatMode(enabled) {
  displayEnabled = enabled;
  const mode = enabled ? "gal_chat" : "text_chat";
  const modeChanged = document.body.dataset.chatMode !== mode;
  document.body.dataset.chatMode = mode;
  galModeButton.setAttribute("aria-pressed", String(enabled));
  textModeButton.setAttribute("aria-pressed", String(!enabled));
  if (modeChanged) {
    galView.setMode(mode);
    refreshHistoryTimeSeparators();
    if (mode === "text_chat") {
      requestAnimationFrame(() => {
        historyList.scrollTop = historyList.scrollHeight;
      });
    }
  }
}

function createHistoryTurnElement(turnId) {
  const turnElement = document.createElement("section");
  turnElement.className = "history-turn";
  turnElement.dataset.turnId = turnId;
  return turnElement;
}

function createHistoryEventElement(event) {
  const row = document.createElement("div");
  const role = ["user", "assistant", "tool"].includes(event.role)
    ? event.role
    : "assistant";
  row.className = `history-event history-event--${role}`;
  row.dataset.eventId = event.event_id;
  row.dataset.createdAt = String(event.created_at ?? "");

  const avatar = document.createElement("img");
  avatar.className = "history-avatar";
  avatar.alt = role === "user" ? "用户头像" : `${displayCharacter}头像`;
  avatar.src = role === "user"
    ? currentUserProfileUrl
    : characterProfileUrl;
  avatar.addEventListener("error", () => {
    avatar.hidden = true;
  });

  const message = document.createElement("div");
  message.className = "history-message";

  const speaker = document.createElement("strong");
  speaker.className = "history-speaker";
  speaker.textContent = role === "user" ? "你" : event.speaker || "未知";
  if (event.type === "vision_description") {
    row.classList.add("history-event--vision");
    speaker.textContent += " · 图片识别结果";
  }
  message.appendChild(speaker);

  const content = String(event.content || "");
  const contentElement = document.createElement("span");
  contentElement.className = "history-content";
  const characters = Array.from(content);

  const collapseLimit = event.type === "vision_description" ? 60 : 20;
  if (["tool_output", "vision_description"].includes(event.type) && characters.length > collapseLimit) {
    const collapsedText = `${characters.slice(0, collapseLimit).join("")}……`;
    let expanded = false;
    contentElement.textContent = collapsedText;

    const toggleButton = document.createElement("button");
    toggleButton.type = "button";
    toggleButton.className = "history-toggle";
    toggleButton.textContent = "展开";
    toggleButton.addEventListener("click", () => {
      expanded = !expanded;
      contentElement.textContent = expanded ? content : collapsedText;
      toggleButton.textContent = expanded ? "收起" : "展开";
    });
    message.append(contentElement, toggleButton);
  } else {
    contentElement.textContent = content;
    message.appendChild(contentElement);
  }

  // 实时事件与分页历史共用此入口；旧记录没有 images 时保持纯文本。
  if (role === "user" && Array.isArray(event.images) && event.images.length) {
    const images = document.createElement("div");
    images.className = "history-images";
    event.images.forEach((filename, index) => {
      const frame = document.createElement("div");
      frame.className = "history-image-frame";
      const image = document.createElement("img");
      image.alt = `用户发送的第 ${index + 1} 张图片`;
      image.loading = "lazy";
      image.decoding = "async";
      // 只替换一次，默认资源失效时也不会循环请求。
      image.addEventListener("error", () => {
        image.src = "/static/imgs/image_load_error.png";
        image.alt = "图片已失效或无法加载";
      }, { once: true });
      image.src = `/api/characters/${encodedCharacter}/history/images/` +
        encodeURIComponent(filename) + "?runtime_id=" + encodeURIComponent(runtimeId);
      frame.appendChild(image);
      images.appendChild(frame);
    });
    message.appendChild(images);
  }

  row.append(avatar, message);

  return row;
}

const historyTimeFormatter = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

function createHistoryTimeSeparator(date, extraClass) {
  const separator = document.createElement("div");
  separator.className = "history-time-separator";
  if (extraClass) separator.classList.add(extraClass);

  const label = document.createElement("span");
  label.textContent = historyTimeFormatter.format(date);
  separator.appendChild(label);
  return separator;
}

function sessionBoundarySeparates(previousEvent, currentEvent) {
  const boundary = historyTurnsElement.querySelector(
    ".history-session-separator",
  );
  return Boolean(
    boundary &&
    previousEvent.compareDocumentPosition(boundary) &
      Node.DOCUMENT_POSITION_FOLLOWING &&
    boundary.compareDocumentPosition(currentEvent) &
      Node.DOCUMENT_POSITION_FOLLOWING
  );
}

function refreshHistoryTimeSeparators() {
  historyTurnsElement.querySelectorAll(".history-gap-separator").forEach(
    (separator) => separator.remove(),
  );
  const events = Array.from(
    historyTurnsElement.querySelectorAll(".history-event"),
  );

  for (let index = 1; index < events.length; index += 1) {
    const previousTime = Number(events[index - 1].dataset.createdAt);
    const currentTime = Number(events[index].dataset.createdAt);
    if (
      !Number.isFinite(previousTime) ||
      !Number.isFinite(currentTime) ||
      currentTime - previousTime <= HISTORY_TIME_GAP_SECONDS ||
      sessionBoundarySeparates(events[index - 1], events[index])
    ) {
      continue;
    }

    const separator = createHistoryTimeSeparator(
      new Date(currentTime * 1000),
      "history-gap-separator",
    );
    events[index].parentNode.insertBefore(separator, events[index]);
  }
}

function insertSessionBoundary() {
  if (
    historyTurnsElement.querySelector(".history-session-separator") ||
    !historyTurnsElement.querySelector(".history-event")
  ) {
    return;
  }
  historyTurnsElement.appendChild(
    createHistoryTimeSeparator(new Date(), "history-session-separator"),
  );
}

function appendHistoryEvent(turnElement, event) {
  if (!event?.event_id || renderedHistoryEventIds.has(event.event_id)) {
    return;
  }
  turnElement.appendChild(createHistoryEventElement(event));
  renderedHistoryEventIds.add(event.event_id);
}

function trimVisibleHistory() {
  while (historyTurns.size > MAX_VISIBLE_HISTORY_TURNS) {
    const oldestTurn = historyTurnsElement.firstElementChild;
    if (!oldestTurn) break;
    historyTurns.delete(oldestTurn.dataset.turnId);
    oldestTurn.remove();
  }
}

function renderHistoryTurns(turns, prepend = false) {
  const previousHeight = historyList.scrollHeight;
  const newTurns = document.createDocumentFragment();

  for (const turn of turns || []) {
    let turnElement = historyTurns.get(turn.turn_id);
    if (!turnElement) {
      turnElement = createHistoryTurnElement(turn.turn_id);
      historyTurns.set(turn.turn_id, turnElement);
      newTurns.appendChild(turnElement);
    }
    for (const event of turn.events || []) {
      appendHistoryEvent(turnElement, event);
    }
  }

  if (prepend) {
    historyTurnsElement.insertBefore(
      newTurns,
      historyTurnsElement.firstChild,
    );
  } else {
    historyTurnsElement.appendChild(newTurns);
  }
  trimVisibleHistory();
  refreshHistoryTimeSeparators();
  if (prepend) {
    historyList.scrollTop += historyList.scrollHeight - previousHeight;
  } else if (document.body.dataset.chatMode === "text_chat") {
    historyList.scrollTop = historyList.scrollHeight;
  }
}

function renderLiveHistoryEvent(event) {
  let turnElement = historyTurns.get(event.turn_id);
  if (!turnElement) {
    turnElement = createHistoryTurnElement(event.turn_id);
    historyTurns.set(event.turn_id, turnElement);
    historyTurnsElement.appendChild(turnElement);
  }
  appendHistoryEvent(turnElement, event);
  trimVisibleHistory();
  refreshHistoryTimeSeparators();
  if (document.body.dataset.chatMode === "text_chat") {
    historyList.scrollTop = historyList.scrollHeight;
  }
  updateHistoryTop();
}

function updateHistoryTop() {
  loadMoreHistoryButton.hidden = true;
  loadMoreHistoryButton.disabled = historyLoading;
  loadMoreHistoryButton.textContent = "加载更多";

  if (historyLoading) {
    historyTopStatus.textContent = "正在加载对话记录……";
    return;
  }
  if (historyLoadError) {
    historyTopStatus.textContent = historyLoadError;
    loadMoreHistoryButton.textContent = "重试";
    loadMoreHistoryButton.hidden = false;
    return;
  }

  if (
    historyTurns.size >= MAX_VISIBLE_HISTORY_TURNS &&
    historyHasMore
  ) {
    historyTopStatus.textContent =
      "在此展示最新100轮对话记录，更多记录请查看：" +
      historyFilePath;
    return;
  }

  if (historyHasMore) {
    historyTopStatus.textContent = "";
    loadMoreHistoryButton.hidden = false;
    return;
  }

  historyTopStatus.textContent = historyTurns.size
    ? "没有更多记录了"
    : "暂无对话记录";
}

async function loadHistoryPage(prepend = false) {
  if (historyLoading || (prepend && !historyHasMore)) return;
  historyLoading = true;
  historyLoadError = "";
  updateHistoryTop();

  const params = new URLSearchParams({
    runtime_id: runtimeId,
    limit: String(HISTORY_PAGE_SIZE),
  });
  if (prepend && historyBeforeTurnId) {
    params.set("before_turn_id", historyBeforeTurnId);
  }

  try {
    const response = await fetch(
      `/api/characters/${encodedCharacter}/history?${params}`,
      { cache: "no-store" },
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(getErrorMessage(data, "加载对话记录失败。"));
    }

    renderHistoryTurns(data.turns, prepend);
    if (!prepend) insertSessionBoundary();
    historyHasMore = Boolean(data.has_more);
    historyBeforeTurnId = data.next_before_turn_id;
    historyFilePath = data.history_file_path || "";
  } catch (error) {
    historyLoadError = "加载对话记录失败：" + error.message;
  } finally {
    historyLoading = false;
    updateHistoryTop();
  }
}

function getErrorMessage(data, fallback) {
  if (typeof data?.detail === "object") {
    return data.detail.message || fallback;
  }
  return data?.detail || fallback;
}

function updateActivityStatus(activities = {}) {
  document.querySelectorAll("[data-status]").forEach((element) => {
    element.classList.toggle(
      "active",
      Boolean(activities[element.dataset.status]),
    );
  });
}

function hasActiveTask(activities = {}) {
  return Object.values(activities).some(Boolean);
}

function scheduleNextPoll(delay = null) {
  if (closingCharacter) return;
  clearTimeout(pollTimer);
  const interval = delay ?? (
    polling_status === "busy" ? BUSY_POLL_MS : IDLE_POLL_MS
  );
  pollTimer = setTimeout(pollStatus, interval);
}

function requestImmediatePoll() {
  if (pollRequestPending) {
    pollAgainImmediately = true;
    return;
  }
  clearTimeout(pollTimer);
  pollStatus();
}

async function fetchReadyDisplay() {
  if (displayPlaying || displayFetchPending || !readyDisplayId) return;

  const displayId = readyDisplayId;
  readyDisplayId = null;
  displayFetchPending = true;

  try {
    const response = await fetch(
      `/api/characters/${encodedCharacter}/displays/` +
        `${encodeURIComponent(displayId)}?runtime_id=` +
        encodeURIComponent(runtimeId),
      { cache: "no-store" },
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(getErrorMessage(data, "获取演出资源失败。"));
    }

    // 领取期间可能恰好完成一次状态轮询；成功后清掉可能残留的旧队首 ID。
    readyDisplayId = null;
    galView.showDialogue(displayCharacter, data.content_split);
    if (data.portrait_url) {
      portrait.src = data.portrait_url;
      portrait.hidden = false;
    }

    if (data.audio_url) {
      displayPlaying = true;
      voiceStatus.textContent = "";
      audio.src = data.audio_url;
      audio.load();
      try {
        await audio.play();
      } catch (error) {
        displayPlaying = false;
        voiceStatus.textContent = "播放失败：" + error.message;
        requestImmediatePoll();
      }
    } else {
      displayPlaying = false;
      voiceStatus.textContent = data.error || "";
      requestImmediatePoll();
    }
  } catch (error) {
    displayPlaying = false;
    voiceStatus.textContent = "获取演出失败：" + error.message;
    requestImmediatePoll();
  } finally {
    displayFetchPending = false;
  }
}

async function fetchReadyHistory() {
  if (historyFetchPending || !readyHistoryId) return;

  const eventId = readyHistoryId;
  readyHistoryId = null;
  historyFetchPending = true;

  try {
    const response = await fetch(
      `/api/characters/${encodedCharacter}/history/events/` +
        `${encodeURIComponent(eventId)}?runtime_id=` +
        encodeURIComponent(runtimeId),
      { cache: "no-store" },
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(getErrorMessage(data, "获取实时对话记录失败。"));
    }
    renderLiveHistoryEvent(data);
  } catch (error) {
    historyTopStatus.textContent = "获取实时对话记录失败：" + error.message;
  } finally {
    historyFetchPending = false;
  }
}

async function pollStatus() {
  if (pollRequestPending || closingCharacter) return;
  pollRequestPending = true;

  try {
    const response = await fetch(
      `/api/characters/${encodedCharacter}/status?runtime_id=` +
        encodeURIComponent(runtimeId),
      { cache: "no-store" },
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(getErrorMessage(data, "无法读取角色状态。"));
    }

    updateChatMode(data.display_enabled);
    updateActivityStatus(data.activities);
    readyDisplayId = data.ready_display_id;
    readyHistoryId = data.ready_history_id;

    if (data.turn_error) {
      voiceStatus.textContent = data.turn_error;
    }

    if (data.memory_consolidation_error) {
      console.error("记忆归档失败：", data.memory_consolidation_error);
      if (
        data.memory_consolidation_error.startsWith(
          "MessageStateValidationError:",
        )
      ) {
        conversationBlocked = true;
        voiceStatus.textContent = data.memory_consolidation_error;
      }
    }

    const backendBusy = (
      data.generation_busy ||
      hasActiveTask(data.activities) ||
      data.display_exist ||
      Boolean(data.ready_history_id)
    );
    if (backendBusy) {
      consecutiveIdleChecks = 0;
      setPollingStatus("busy");
    } else {
      consecutiveIdleChecks += 1;
      if (consecutiveIdleChecks >= IDLE_CONFIRM_COUNT) {
        setPollingStatus("idle");
      }
    }

    if (!displayPlaying) {
      await fetchReadyDisplay();
    }
    await fetchReadyHistory();
    applyControlState();
  } catch (error) {
    consecutiveIdleChecks = 0;
    setPollingStatus("busy");
    voiceStatus.textContent = "状态检查失败：" + error.message;
  } finally {
    pollRequestPending = false;
    if (pollAgainImmediately) {
      pollAgainImmediately = false;
      scheduleNextPoll(0);
    } else {
      scheduleNextPoll();
    }
  }
}

async function closeCharacter() {
  if (!runtimeId) {
    voiceStatus.textContent = "缺少角色运行时标识，请返回角色选择页重新打开。";
    return;
  }

  closingCharacter = true;
  applyControlState();
  clearTimeout(pollTimer);
  try {
    const response = await fetch(
      `/api/characters/${encodedCharacter}/runtimes/` +
        encodeURIComponent(runtimeId),
      { method: "DELETE" },
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(getErrorMessage(data, "角色资源释放失败。"));
    }

    window.close();
    voiceStatus.textContent = data.released
      ? "角色资源已释放，可以关闭当前页面。"
      : "本次角色资源已经释放或已被重新初始化，可以关闭当前页面。";
  } catch (error) {
    closingCharacter = false;
    applyControlState();
    voiceStatus.textContent = "关闭角色失败：" + error.message;
    scheduleNextPoll();
  }
}

async function setChatMode(mode) {
  const requestedState = mode === "gal_chat";
  if (requestedState === displayEnabled) return;
  galModeButton.disabled = true;
  textModeButton.disabled = true;

  try {
    const response = await fetch(
      `/api/characters/${encodedCharacter}/display`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: requestedState,
          runtime_id: runtimeId,
        }),
      },
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(getErrorMessage(data, "演出设置修改失败。"));
    }

    updateChatMode(data.display_enabled);
    if (!data.display_enabled && !audio.paused) {
      audio.pause();
      displayPlaying = false;
    }
    voiceStatus.textContent = "";
  } catch (error) {
    voiceStatus.textContent = "演出设置修改失败：" + error.message;
  } finally {
    applyControlState();
    requestImmediatePoll();
  }
}

async function sendMessage() {
  if (sendButton.disabled || sendInFlight) return;
  const message = inputBox.value.trim();
  if (!message && !pendingImages.length) return;

  // 与后端忙碌锁互补：读取文件、上传期间后端可能仍报告空闲。
  sendInFlight = true;
  document.body.dataset.sendInFlight = "true";
  attachmentMenu.hidden = true;
  attachmentButton.setAttribute("aria-expanded", "false");
  voiceStatus.textContent = "";
  if (displayEnabled) galView.showDialogue("你", message || `[用户发送了${pendingImages.length}张图片]`);
  consecutiveIdleChecks = 0;
  setPollingStatus("busy");
  requestImmediatePoll();

  try {
    if (displayEnabled) await unlockAudio();
    const images = await Promise.all(pendingImages.map(async ({ file }) => ({
      data_url: await fileDataUrl(file),
    })));
    const response = await fetch(
      `/api/characters/${encodedCharacter}/chat`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, runtime_id: runtimeId, images }),
      },
    );
    const data = await response.json();
    if (response.status === 409 && data.detail?.code === "message_state_invalid") {
      conversationBlocked = true;
      voiceStatus.textContent = data.detail.message;
      return;
    }
    if (!response.ok) throw new Error(getErrorMessage(data, "请求失败。"));
    updateChatMode(data.display_enabled);
    inputBox.value = "";
    clearImageDraft();
    // image_description 仅表示本次识别状态；历史由 FIFO 统一交付，避免重复插入。
  } catch (error) {
    voiceStatus.textContent = "请求失败：" + error.message;
  } finally {
    sendInFlight = false;
    document.body.dataset.sendInFlight = "false";
    applyControlState();
    requestImmediatePoll();
  }
}

async function finishCurrentDisplay(event) {
  if (!displayPlaying) return;
  if (event.type === "ended") {
    const finishedAudioUrl = audio.src;
    // 停顿期间保持播放标记，防止状态轮询提前领取下一段演出。
    await new Promise((resolve) => setTimeout(resolve, DISPLAY_GAP_MS));
    // 异常处理可能已经开始下一段，旧回调不能清除新一段的播放标记。
    if (!displayPlaying || audio.src !== finishedAudioUrl) return;
  }
  displayPlaying = false;
  if (closingCharacter || !displayEnabled) return;
  if (readyDisplayId) {
    fetchReadyDisplay();
  } else {
    requestImmediatePoll();
  }
}

sendButton.addEventListener("click", sendMessage);
closeCharacterButton.addEventListener("click", closeCharacter);
galModeButton.addEventListener("click", () => setChatMode("gal_chat"));
textModeButton.addEventListener("click", () => setChatMode("text_chat"));
assetSelectButton.addEventListener("click", () => {
  chooseFrontendAsset("background_image_gal");
});
assetFileInput.addEventListener("change", () => {
  uploadFrontendAsset(assetFileInput.files?.[0]);
});
historyList.addEventListener("click", (event) => {
  if (
    document.body.dataset.chatMode === "text_chat" &&
    event.target.closest(".history-event--user .history-avatar")
  ) {
    chooseFrontendAsset("user_profile");
  }
});
loadMoreHistoryButton.addEventListener("click", () => {
  loadHistoryPage(historyTurns.size > 0);
});

inputBox.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    sendMessage();
  }
});

audio.addEventListener("ended", finishCurrentDisplay);
audio.addEventListener("error", finishCurrentDisplay);
portrait.addEventListener("error", () => {
  portrait.hidden = true;
});

async function initializeChatPage() {
  applyControlState();
  await loadTrueCharacterName();
  await loadFrontendAssets();
  await themeController.load();
  await portraitLayoutController.load();
  await loadDisplayBootstrap();
  await loadHistoryPage();
  pollStatus();
}

initializeChatPage();
