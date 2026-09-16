const characterGroups = document.getElementById("characterGroups");
const toggleAllGroupsButton = document.getElementById(
  "toggleAllGroupsButton",
);
const groupMenu = document.getElementById("groupMenu");
const deleteGroupDialog = document.getElementById("deleteGroupDialog");
const deleteGroupMessage = document.getElementById("deleteGroupMessage");
const skipDeleteConfirmation = document.getElementById(
  "skipDeleteConfirmation",
);
const characterSettingDialog = document.getElementById(
  "characterSettingDialog",
);
const characterSettingTitle = document.getElementById(
  "characterSettingTitle",
);
const characterSettingContent = document.getElementById(
  "characterSettingContent",
);
const ENTRY_STYLESHEET_URL = new URL(
  "/static/css/character-selection.css?v=20260829-1",
  window.location.origin,
).href;
const FAVOURITE_GROUP_KEY = "system:favourite";
const UNGROUPED_GROUP_KEY = "system:ungrouped";
const SCENE_MODE_DETAILS = {
  sandbox: {
    label: "沙",
    name: "沙盒",
    description: "对话以设定的时间和场景为准，不提供网络搜索；可通过括号内容补充时间、场景、动作和剧情引导。",
  },
  realtime: {
    label: "时",
    name: "实时",
    description: "AI伙伴会获得现实时间，并支持通过网络搜索获取最新信息。",
  },
};

let characters = [];
let customGroups = [];
let skipGroupDeleteConfirmation = false;
let characterSettingLoading = false;
let cardsDisabled = false;
const expandedGroups = new Set([FAVOURITE_GROUP_KEY]);

function setCardsDisabled(disabled) {
  cardsDisabled = disabled;
  characterGroups.querySelectorAll(
    ".character-card, .favour-button, .group-button, " +
      ".group-toggle, .group-action",
  ).forEach((button) => {
    button.disabled = disabled || button.dataset.fixedDisabled === "true";
  });
  toggleAllGroupsButton.disabled = (
    disabled || !characterGroups.children.length
  );
  setCharacterSettingButtonsDisabled(characterSettingLoading);
}

function createProfilePlaceholder(page, displayName) {
  const placeholder = page.createElement("div");
  placeholder.className = "profile-placeholder";
  placeholder.textContent = displayName.slice(0, 1).toUpperCase();
  return placeholder;
}

function createProfile(page, displayName, profileUrl) {
  if (!profileUrl) return createProfilePlaceholder(page, displayName);

  const image = page.createElement("img");
  image.className = "profile";
  image.src = profileUrl;
  image.alt = `${displayName} 的头像`;
  image.addEventListener("error", () => {
    image.replaceWith(createProfilePlaceholder(page, displayName));
  }, { once: true });
  return image;
}

function prepareMessagePage(page, isError) {
  if (!page.head.querySelector("meta[name='viewport']")) {
    const viewport = page.createElement("meta");
    viewport.name = "viewport";
    viewport.content = "width=device-width, initial-scale=1";
    page.head.appendChild(viewport);
  }
  if (!page.head.querySelector("link[data-entry-stylesheet]")) {
    const stylesheet = page.createElement("link");
    stylesheet.rel = "stylesheet";
    stylesheet.href = ENTRY_STYLESHEET_URL;
    stylesheet.dataset.entryStylesheet = "true";
    page.head.appendChild(stylesheet);
  }
  page.body.className = isError
    ? "loading-page initialization-error"
    : "loading-page";
}

function createMessagePage(
  targetWindow,
  { title, heading, message, displayName, profileUrl, isError = false },
) {
  const page = targetWindow.document;
  page.documentElement.lang = "zh-CN";
  page.title = title;
  prepareMessagePage(page, isError);

  const main = page.createElement("main");
  main.className = "loading-shell";
  const card = page.createElement("section");
  card.className = "loading-card";
  const avatarFrame = page.createElement("div");
  avatarFrame.className = "loading-avatar-frame";
  const headingElement = page.createElement("h1");
  const messageElement = page.createElement("p");
  messageElement.className = "loading-message";
  headingElement.textContent = heading;
  messageElement.textContent = message;
  avatarFrame.appendChild(createProfile(page, displayName, profileUrl));
  card.append(avatarFrame, headingElement, messageElement);
  main.appendChild(card);
  page.body.replaceChildren(main);
  return card;
}

function showLoadingPage(chatWindow, displayName, profileUrl) {
  createMessagePage(chatWindow, {
    title: `正在加载 ${displayName}`,
    heading: `正在初始化 ${displayName}`,
    message: (
      "正在加载角色设定、记忆和语音模型，请稍候。" +
      "初始化完成后将自动进入对话页面。"
    ),
    displayName,
    profileUrl,
  });
}

function showInitializationError(
  chatWindow,
  displayName,
  profileUrl,
  errorMessage,
) {
  const card = createMessagePage(chatWindow, {
    title: `${displayName} 初始化失败`,
    heading: `${displayName} 初始化失败`,
    message: errorMessage,
    displayName,
    profileUrl,
    isError: true,
  });
  const page = chatWindow.document;
  const actions = page.createElement("div");
  actions.className = "loading-actions";

  const characterSelectionLink = page.createElement("a");
  characterSelectionLink.href = "/";
  characterSelectionLink.textContent = "返回角色选择";

  const closeButton = page.createElement("button");
  closeButton.type = "button";
  closeButton.textContent = "关闭窗口";
  closeButton.addEventListener("click", () => chatWindow.close());

  actions.append(characterSelectionLink, closeButton);
  card.appendChild(actions);
}

async function selectCharacter(characterName, displayName, profileUrl) {
  // 必须在点击事件中立即创建窗口，否则异步请求结束后可能被浏览器拦截。
  const chatWindow = window.open("about:blank", "_blank");
  if (!chatWindow) {
    window.alert("浏览器阻止了新窗口，请允许本站打开弹窗后重试。");
    return;
  }
  chatWindow.opener = null;
  showLoadingPage(chatWindow, displayName, profileUrl);
  setCardsDisabled(true);

  try {
    const encodedName = encodeURIComponent(characterName);
    const response = await fetch(`/api/characters/${encodedName}/select`, {
      method: "POST",
    });
    const data = await response.json();
    if (!response.ok) {
      const detail = data.detail;
      throw new Error(
        typeof detail === "object"
          ? detail.message
          : detail || "角色初始化失败。",
      );
    }

    if (chatWindow.closed) return;
    chatWindow.location.replace(data.chat_url);
  } catch (error) {
    if (!chatWindow.closed) {
      showInitializationError(
        chatWindow,
        displayName,
        profileUrl,
        error.message,
      );
    }
  } finally {
    // 选择页保持打开，以便继续选择其他角色。
    setCardsDisabled(false);
  }
}

function customGroupKey(group) {
  return `custom:${group}`;
}

function getErrorMessage(data, fallback) {
  if (typeof data?.detail === "object") {
    return data.detail.message || fallback;
  }
  return data?.detail || fallback;
}

function createSceneModeBadge(sceneMode) {
  const mode = SCENE_MODE_DETAILS[sceneMode];
  if (!mode?.label) return null;

  const badge = document.createElement("span");
  badge.className = "scene-mode-badge";
  badge.dataset.sceneMode = sceneMode;
  badge.textContent = mode.label;
  badge.title = `当前为${mode.name}模式。\n${mode.description}\n` +
    "如需切换，请先关闭程序，修改角色配置文件 [character] 下的 scene_mode，" +
    "按需将背景数据导入目标模式对应的数据库，再重新运行代码。";
  badge.setAttribute("role", "img");
  badge.setAttribute("aria-label", badge.title);
  return badge;
}

function setCharacterSettingButtonsDisabled(disabled) {
  characterGroups.querySelectorAll(".character-setting-button").forEach(
    (button) => { button.disabled = cardsDisabled || disabled; },
  );
}

async function showCharacterSetting(character) {
  if (characterSettingLoading) return;
  characterSettingLoading = true;
  setCharacterSettingButtonsDisabled(true);
  characterSettingTitle.textContent = `${character.display_name} 的角色设定`;
  characterSettingContent.textContent = "正在读取角色设定……";
  if (!characterSettingDialog.open) characterSettingDialog.showModal();

  try {
    const encodedName = encodeURIComponent(character.name);
    const response = await fetch(
      `/api/characters/${encodedName}/character-setting`,
      { cache: "no-store" },
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(getErrorMessage(data, "角色设定读取失败。"));
    }
    // 角色设定必须作为纯文本展示，不能解释其中的 HTML 内容。
    characterSettingContent.textContent = data.content;
  } catch (error) {
    characterSettingContent.textContent =
      `角色设定读取失败：${error.message}`;
  } finally {
    characterSettingLoading = false;
    setCharacterSettingButtonsDisabled(false);
  }
}

function renderCharacter(character, grid) {
  const wrapper = document.createElement("div");
  wrapper.className = "character-card-wrapper";
  wrapper.dataset.characterName = character.name;

  const card = document.createElement("button");
  card.className = "character-card";
  card.type = "button";
  card.addEventListener("click", () => (
    selectCharacter(
      character.name,
      character.display_name,
      character.profile_url,
    )
  ));

  card.appendChild(createProfile(
    document,
    character.display_name,
    character.profile_url,
  ));

  const name = document.createElement("span");
  name.className = "character-name";
  name.textContent = character.display_name;
  card.appendChild(name);

  const favourButton = document.createElement("button");
  favourButton.className = "favour-button";
  favourButton.type = "button";
  updateFavourButton(favourButton, character);
  favourButton.addEventListener("click", () => (
    toggleCharacterFavour(character, favourButton)
  ));

  const groupButton = document.createElement("button");
  groupButton.className = "group-button";
  groupButton.type = "button";
  groupButton.textContent = "↪";
  groupButton.title = "移至分组";
  groupButton.setAttribute(
    "aria-label",
    `将${character.display_name}移至分组`,
  );
  groupButton.addEventListener("click", () => {
    openGroupMenu(character, groupButton);
  });

  // 独立于角色主按钮，查看模式和操作工具时不会触发角色初始化。
  const tools = document.createElement("div");
  tools.className = "character-card-tools";
  const modeBadge = createSceneModeBadge(character.scene_mode);
  const settingButton = document.createElement("button");
  settingButton.className = "character-setting-button";
  settingButton.type = "button";
  settingButton.textContent = "📑";
  settingButton.title = "查看角色设定";
  settingButton.setAttribute(
    "aria-label",
    `查看${character.display_name}的角色设定`,
  );
  settingButton.addEventListener("click", () => {
    showCharacterSetting(character);
  });

  const info = document.createElement("div");
  info.className = "character-card-info";
  if (modeBadge) info.appendChild(modeBadge);
  info.appendChild(settingButton);
  tools.append(favourButton, groupButton);
  wrapper.append(card, info, tools);
  grid.appendChild(wrapper);
}

function updateFavourButton(button, character) {
  const isFavourite = Boolean(character.favour);
  button.textContent = isFavourite ? "★" : "☆";
  button.classList.toggle("is-active", isFavourite);
  button.setAttribute("aria-pressed", String(isFavourite));
  button.setAttribute(
    "aria-label",
    `${isFavourite ? "取消喜爱" : "设为喜爱"}${character.display_name}`,
  );
  button.title = isFavourite ? "取消喜爱" : "设为喜爱";
}

async function toggleCharacterFavour(character, button) {
  const previousValue = Boolean(character.favour);
  character.favour = !previousValue;
  updateFavourButton(button, character);
  closeGroupMenu();
  setCardsDisabled(true);

  try {
    const encodedName = encodeURIComponent(character.name);
    const response = await fetch(
      `/api/characters/${encodedName}/favour`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ favour: character.favour }),
      },
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "角色喜爱状态保存失败。");
    }

    character.favour = data.favour;
    await loadSelectionData();
  } catch (error) {
    character.favour = previousValue;
    updateFavourButton(button, character);
    window.alert(error.message);
  } finally {
    setCardsDisabled(false);
  }
}

function createMenuButton(label, action, { current = false } = {}) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "group-menu-item";
  button.textContent = current ? `✓ ${label}` : label;
  button.addEventListener("click", () => {
    closeGroupMenu();
    action();
  });
  groupMenu.appendChild(button);
}

function openGroupMenu(character, anchor) {
  groupMenu.replaceChildren();
  createMenuButton("＋ 创建新分组", () => createGroupForCharacter(character));
  const divider = document.createElement("hr");
  groupMenu.appendChild(divider);
  createMenuButton("喜爱", () => setCharacterFavourite(character), {
    current: character.favour,
  });
  createMenuButton(
    character.favour ? "未分组（同时取消喜爱）" : "未分组",
    () => moveCharacterToGroup(character, ""),
    { current: !character.favour && !character.group },
  );
  customGroups.forEach((group) => {
    createMenuButton(
      group,
      () => moveCharacterToGroup(character, group),
      { current: character.group === group },
    );
  });

  const rect = anchor.getBoundingClientRect();
  groupMenu.style.top = `${rect.bottom + 6}px`;
  groupMenu.style.left = `${Math.max(8, rect.right - 220)}px`;
  groupMenu.hidden = false;
}

function closeGroupMenu() {
  groupMenu.hidden = true;
  groupMenu.replaceChildren();
}

async function setCharacterFavourite(character) {
  if (character.favour) return;
  const placeholder = document.createElement("button");
  await toggleCharacterFavour(character, placeholder);
}

async function createGroupForCharacter(character) {
  const group = window.prompt("请输入新分组名称：");
  if (group === null) return;
  const normalizedGroup = group.trim();
  if (!normalizedGroup) {
    window.alert("分组名称不能为空。");
    return;
  }
  await moveCharacterToGroup(character, normalizedGroup);
}

async function moveCharacterToGroup(character, group) {
  closeGroupMenu();
  setCardsDisabled(true);
  try {
    const encodedName = encodeURIComponent(character.name);
    const response = await fetch(
      `/api/characters/${encodedName}/group`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ group }),
      },
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(getErrorMessage(data, "角色分组保存失败。"));
    }

    if (data.group) {
      expandedGroups.add(customGroupKey(data.group));
    } else {
      expandedGroups.add(UNGROUPED_GROUP_KEY);
    }
    await loadSelectionData();
  } catch (error) {
    window.alert(error.message);
  } finally {
    setCardsDisabled(false);
  }
}

function createGroupSection(key, label, members, customIndex = null) {
  const section = document.createElement("section");
  section.className = "character-group";
  section.dataset.groupKey = key;

  const header = document.createElement("header");
  header.className = "group-header";
  const toggleButton = document.createElement("button");
  toggleButton.type = "button";
  toggleButton.className = "group-toggle";
  toggleButton.setAttribute(
    "aria-expanded",
    String(expandedGroups.has(key)),
  );
  const chevron = document.createElement("span");
  chevron.className = "group-chevron";
  chevron.classList.toggle("is-expanded", expandedGroups.has(key));
  chevron.textContent = "▷";
  const name = document.createElement("span");
  name.textContent = label;
  const count = document.createElement("span");
  count.className = "group-count";
  count.textContent = String(members.length);
  toggleButton.append(chevron, name, count);
  toggleButton.addEventListener("click", () => toggleGroup(key));
  header.appendChild(toggleButton);

  if (customIndex !== null) {
    const actions = document.createElement("div");
    actions.className = "group-actions";
    const upButton = createGroupAction("↑", "上移分组", () => (
      moveGroupOrder(label, "up")
    ));
    upButton.dataset.fixedDisabled = String(customIndex === 0);
    upButton.disabled = customIndex === 0;
    const downButton = createGroupAction("↓", "下移分组", () => (
      moveGroupOrder(label, "down")
    ));
    downButton.dataset.fixedDisabled = String(
      customIndex === customGroups.length - 1,
    );
    downButton.disabled = customIndex === customGroups.length - 1;
    const deleteButton = createGroupAction("删除", "删除分组", () => (
      deleteGroup(label)
    ));
    deleteButton.classList.add("delete-group-button");
    actions.append(upButton, downButton, deleteButton);
    header.appendChild(actions);
  }

  const grid = document.createElement("div");
  grid.className = "character-grid";
  grid.hidden = !expandedGroups.has(key);
  members.forEach((character) => renderCharacter(character, grid));
  section.append(header, grid);
  return section;
}

function createGroupAction(text, label, action) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "group-action";
  button.textContent = text;
  button.title = label;
  button.setAttribute("aria-label", label);
  button.addEventListener("click", action);
  return button;
}

function renderGroups() {
  characterGroups.replaceChildren();
  const favouriteCharacters = characters.filter((character) => (
    character.favour
  ));
  const ungroupedCharacters = characters.filter((character) => (
    !character.favour && !character.group
  ));

  if (favouriteCharacters.length) {
    characterGroups.appendChild(createGroupSection(
      FAVOURITE_GROUP_KEY,
      "喜爱",
      favouriteCharacters,
    ));
  }
  if (ungroupedCharacters.length) {
    characterGroups.appendChild(createGroupSection(
      UNGROUPED_GROUP_KEY,
      "未分组",
      ungroupedCharacters,
    ));
  }
  customGroups.forEach((group, index) => {
    const members = characters.filter((character) => (
      character.group === group
    ));
    if (members.length) {
      characterGroups.appendChild(createGroupSection(
        customGroupKey(group),
        group,
        members,
        index,
      ));
    }
  });
  updateToggleAllButton();
}

function toggleGroup(key) {
  if (expandedGroups.has(key)) {
    expandedGroups.delete(key);
  } else {
    expandedGroups.add(key);
  }
  renderGroups();
}

function updateToggleAllButton() {
  const sections = Array.from(
    characterGroups.querySelectorAll(".character-group"),
  );
  const allExpanded = (
    sections.length > 0 &&
    sections.every((section) => expandedGroups.has(section.dataset.groupKey))
  );
  toggleAllGroupsButton.textContent = allExpanded ? "折叠全部" : "展开全部";
  toggleAllGroupsButton.disabled = sections.length === 0;
}

function toggleAllGroups() {
  const keys = Array.from(
    characterGroups.querySelectorAll(".character-group"),
    (section) => section.dataset.groupKey,
  );
  const allExpanded = keys.every((key) => expandedGroups.has(key));
  keys.forEach((key) => {
    if (allExpanded) expandedGroups.delete(key);
    else expandedGroups.add(key);
  });
  renderGroups();
}

async function moveGroupOrder(group, direction) {
  setCardsDisabled(true);
  try {
    const response = await fetch("/api/character-groups/order", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ group, direction }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(getErrorMessage(data, "分组顺序保存失败。"));
    }
    customGroups = data.groups;
    renderGroups();
  } catch (error) {
    window.alert(error.message);
  } finally {
    setCardsDisabled(false);
  }
}

function confirmGroupDeletion(group) {
  if (skipGroupDeleteConfirmation) return Promise.resolve(true);
  deleteGroupMessage.textContent = (
    `确定要删除“${group}”吗？其中的角色将移出该分组。`
  );
  skipDeleteConfirmation.checked = false;
  deleteGroupDialog.returnValue = "";
  deleteGroupDialog.showModal();

  return new Promise((resolve) => {
    deleteGroupDialog.addEventListener("close", () => {
      const confirmed = deleteGroupDialog.returnValue === "confirm";
      if (confirmed && skipDeleteConfirmation.checked) {
        skipGroupDeleteConfirmation = true;
      }
      resolve(confirmed);
    }, { once: true });
  });
}

async function deleteGroup(group) {
  if (!await confirmGroupDeletion(group)) return;
  setCardsDisabled(true);
  try {
    const response = await fetch("/api/character-groups", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ group }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(getErrorMessage(data, "删除分组失败。"));
    }
    expandedGroups.delete(customGroupKey(group));
    await loadSelectionData();
  } catch (error) {
    window.alert(error.message);
  } finally {
    setCardsDisabled(false);
  }
}

function discoverGroups(characterList) {
  return characterList.reduce((groups, character) => {
    if (character.group && !groups.includes(character.group)) {
      groups.push(character.group);
    }
    return groups;
  }, []);
}

async function loadSelectionData() {
  try {
    const response = await fetch("/api/characters", {
      cache: "no-store",
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "无法读取角色列表。");
    }
    if (!data.characters.length) {
      window.alert("characters 目录中没有可用角色。");
      return;
    }

    characters = data.characters;
    const discoveredGroups = discoverGroups(characters);
    try {
      const groupResponse = await fetch("/api/character-groups", {
        cache: "no-store",
      });
      const groupData = await groupResponse.json();
      if (!groupResponse.ok) {
        throw new Error(getErrorMessage(groupData, "无法读取分组顺序。"));
      }
      customGroups = groupData.groups;
    } catch (error) {
      // 分组顺序损坏不应阻止用户选择角色。
      console.warn(error);
      customGroups = discoveredGroups;
    }
    renderGroups();
  } catch (error) {
    window.alert(error.message);
  }
}

toggleAllGroupsButton.addEventListener("click", toggleAllGroups);
document.addEventListener("click", (event) => {
  if (
    !groupMenu.hidden &&
    !event.target.closest(".group-menu") &&
    !event.target.closest(".group-button")
  ) {
    closeGroupMenu();
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeGroupMenu();
});

loadSelectionData();
