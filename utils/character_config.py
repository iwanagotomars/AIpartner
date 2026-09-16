from copy import deepcopy
from pathlib import Path
from threading import Lock
from typing import Any
import tomllib
import os
import tomlkit
from uuid import uuid4


DEFAULT_CONFIG_FILENAME = "character_config.default.toml"
CHARACTER_CONFIG_FILENAME = "character_config.toml"
FAVOURITE_GROUP_NAME = "喜爱"
UNGROUPED_GROUP_NAME = "未分组"
MAX_CHARACTER_GROUP_LENGTH = 30
VALID_SCENE_MODES = {"realtime", "sandbox"}
TRANSLATION_LANGUAGE_MAP = {
    "中文": "Chinese",
    "英语": "English",
    "德语": "German",
    "意大利语": "Italian",
    "葡萄牙语": "Portuguese",
    "西班牙语": "Spanish",
    "日语": "Japanese",
    "韩语": "Korean",
    "法语": "French",
    "俄语": "Russian",
}
DEFAULT_CHAT_THEME = "default"
VALID_CHAT_THEMES = {
    DEFAULT_CHAT_THEME,
    "rose_red",
    "sakura_pink",
    "royal_gold",
    "sky_blue",
    "sprout_green",
    "warm_orange",
    "mystic_purple",
    "midnight_black",
}
_LEGACY_FIELDS = {
    "true_character_name": "character",
    "scene_mode": "character",
    "chat_theme": "frontend",
    "favour": "frontend",
    "group": "frontend",
}
_CONFIG_WRITE_LOCK = Lock()


def _read_toml(path: Path) -> dict[str, Any]:
    """读取 TOML；配置错误应在角色初始化阶段直接暴露。"""
    try:
        with path.open("rb") as file:
            return tomllib.load(file)
    except FileNotFoundError as error:
        raise ValueError(f"未找到默认角色配置文件：{path}") from error
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"角色配置文件格式错误：{path}\n{error}") from error


def merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """递归合并配置，角色配置仅需填写想覆盖的项目。"""
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_config(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def get_config_value(config: dict[str, Any], path: str) -> Any:
    """使用形如 memory.context.base_message_turn 的路径读取配置。"""
    value: Any = config
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            raise ValueError(f"角色配置缺少必要项目：{path}")
        value = value[key]
    return value


def get_int_config(
    config: dict[str, Any],
    path: str,
    *,
    minimum: int = 1,
) -> int:
    value = get_config_value(config, path)
    # bool 是 int 的子类，但不应被当作数值配置接受。
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"角色配置 {path} 必须是不小于 {minimum} 的整数")
    return value


def get_string_list_config(config: dict[str, Any], path: str) -> list[str]:
    """读取由非空字符串组成的列表配置。"""
    value = get_config_value(config, path)
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip()
        for item in value
    ):
        raise ValueError(f"角色配置 {path} 必须是非空字符串列表")
    return [item.strip() for item in value]


def normalize_translation_language(
    value: Any,
    path: str,
    *,
    allow_empty: bool = False,
) -> str:
    """将中英文语言配置规范为 TTS 接受的标准英文名称。"""
    if not isinstance(value, str):
        raise ValueError(f"角色配置 {path} 必须是字符串")

    language = value.strip()
    if not language:
        if allow_empty:
            return ""
        raise ValueError(f"角色配置 {path} 不能为空")

    if language in TRANSLATION_LANGUAGE_MAP:
        return TRANSLATION_LANGUAGE_MAP[language]
    if language in TRANSLATION_LANGUAGE_MAP.values():
        return language

    valid_languages = "、".join(
        [
            *TRANSLATION_LANGUAGE_MAP.keys(),
            *TRANSLATION_LANGUAGE_MAP.values(),
        ]
    )
    raise ValueError(
        f"角色配置 {path} 无效：{value!r}。有效值为：{valid_languages}"
    )


def get_memory_root(character_dir: Path, scene_mode: str) -> Path:
    """返回当前模式独立的记忆根目录。"""
    if scene_mode not in VALID_SCENE_MODES:
        raise ValueError(f"非法 scene_mode：{scene_mode!r}")
    directory_name = (
        "memory_db" if scene_mode == "realtime" else "memory_db_sandbox"
    )
    return character_dir / directory_name


def normalize_chat_theme(value: Any) -> str:
    """视觉配置错误不应阻止角色对话，未知值回退到简洁白。"""
    return (
        value
        if isinstance(value, str) and value in VALID_CHAT_THEMES
        else DEFAULT_CHAT_THEME
    )


def normalize_favour(value: Any) -> bool:
    """无效的界面喜爱配置按未喜爱处理，不阻止角色列表加载。"""
    return value if isinstance(value, bool) else False


def validate_character_group(value: Any, *, allow_empty: bool = True) -> str:
    """校验用户分组名；空字符串仅用于表示未指定自定义分组。"""
    if not isinstance(value, str):
        raise ValueError("group 必须是字符串")
    group = value.strip()
    if not group:
        if allow_empty:
            return ""
        raise ValueError("分组名称不能为空")
    if len(group) > MAX_CHARACTER_GROUP_LENGTH:
        raise ValueError(
            f"分组名称不能超过 {MAX_CHARACTER_GROUP_LENGTH} 个字符"
        )
    if group in {FAVOURITE_GROUP_NAME, UNGROUPED_GROUP_NAME}:
        raise ValueError(f"'{group}' 是系统保留分组名称")
    if any(ord(character) < 32 or ord(character) == 127 for character in group):
        raise ValueError("分组名称不能包含控制字符")
    return group


def normalize_character_group(value: Any) -> str:
    """手写分组配置无效时按未分组处理，避免阻断角色加载。"""
    try:
        return validate_character_group(value)
    except ValueError:
        return ""


def _migrate_document(document: Any) -> tuple[Any, bool]:
    """按原文顺序聚合旧字段；不补默认值，已有新值优先。"""
    for section in ("character", "frontend"):
        if section in document and not isinstance(document[section], dict):
            raise ValueError(f"角色配置 [{section}] 必须是 TOML 表")
    if not any(key in document for key in _LEGACY_FIELDS):
        return document, False

    # 新分区按第一次遇到旧字段的顺序建立；已有分区仍留在原位。
    new_sections = {}
    kept = []
    pending = []
    seen_key = False
    header_count = 0
    for key, item in document.body:
        if key is None:
            pending.append((key, item))
            continue
        name = key.key
        section = _LEGACY_FIELDS.get(name)
        if not seen_key:
            # 文件开头的注释统一作为总说明保留，不猜测其语义归属。
            kept.extend(pending)
            header_count = len(kept)
            pending = []
            seen_key = True
        if section is None:
            kept.extend(pending)
            kept.append((key, item))
        else:
            if section in document:
                target = document[section]
            else:
                target = new_sections.setdefault(section, tomlkit.table())
            if name not in target:
                # 空行前的独立注释留在原处，仅移动紧邻字段的说明。
                split = next(
                    (i + 1 for i in range(len(pending) - 1, -1, -1)
                     if pending[i][1].as_string().strip() == ""), 0,
                )
                kept.extend(pending[:split])
                for comment_key, comment in pending[split:]:
                    target.append(comment_key, comment)
                target.append(key, item)
            else:
                kept.extend(pending)
                if target[name] != item:
                    print(f"[配置迁移] {section}.{name} 优先，已移除旧顶层 {name}。")
        pending = []
    kept.extend(pending)

    # 保留所有无关条目；新分区插在原有第一个表之前，避免顶层键落入表中。
    insert_at = next(
        (i for i, (_, item) in enumerate(kept)
         if isinstance(item, (tomlkit.items.Table, tomlkit.items.AoT))), len(kept),
    )
    # 原有表前面的注释仍紧邻该表，文件总说明保持在最前面。
    while insert_at > header_count and kept[insert_at - 1][0] is None:
        insert_at -= 1
    result = tomlkit.document()
    entries = kept[:insert_at] + list(new_sections.items()) + kept[insert_at:]
    for key, item in entries:
        result.append(key, item)
    return result, True


def _write_document(path: Path, document: Any) -> None:
    """调用方持有写锁；解析检查后原子替换，失败时原文件不被截断。"""
    text = tomlkit.dumps(document)
    tomllib.loads(text)
    temporary_path = path.with_name(f".{uuid4().hex}.toml.tmp")
    try:
        with temporary_path.open("w", encoding="utf-8", newline="") as file:
            file.write(text)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _read_character_document(path: Path) -> Any:
    # newline="" 保留原有换行，避免仅加载就改写配置格式。
    with path.open("r", encoding="utf-8", newline="") as file:
        return tomlkit.parse(file.read())


def _load_character_override(path: Path) -> dict[str, Any]:
    with _CONFIG_WRITE_LOCK:
        if not path.is_file():
            return {}
        document = _read_character_document(path)
        document, changed = _migrate_document(document)
        if changed:
            _write_document(path, document)
        return document.unwrap()


def _save_frontend_config(
    characters_dir: Path, character_name: str, values: dict[str, Any],
) -> None:
    """三个界面接口共用：先迁移，再只写入指定的 frontend 字段。"""
    characters_dir = characters_dir.resolve()
    character_dir = (characters_dir / character_name).resolve()
    if character_dir.parent != characters_dir or not character_dir.is_dir():
        raise ValueError(f"角色 '{character_name}' 不存在")
    path = character_dir / CHARACTER_CONFIG_FILENAME
    with _CONFIG_WRITE_LOCK:
        document = _read_character_document(path) if path.is_file() else tomlkit.document()
        document, _ = _migrate_document(document)
        if "frontend" not in document:
            document["frontend"] = tomlkit.table()
        for key, value in values.items():
            document["frontend"][key] = value
        _write_document(path, document)


def save_character_chat_theme(
    characters_dir: Path, character_name: str, chat_theme: str,
) -> None:
    if chat_theme not in VALID_CHAT_THEMES:
        raise ValueError(f"不支持的聊天主题：{chat_theme}")
    _save_frontend_config(characters_dir, character_name, {"chat_theme": chat_theme})


def save_character_favour(
    characters_dir: Path, character_name: str, favour: bool,
) -> None:
    if not isinstance(favour, bool):
        raise ValueError("favour 必须是布尔值")
    _save_frontend_config(characters_dir, character_name, {"favour": favour})


def save_character_group(
    characters_dir: Path, character_name: str, group: str, *, clear_favour: bool = False,
) -> None:
    values = {"group": validate_character_group(group)}
    if clear_favour:
        values["favour"] = False
    _save_frontend_config(characters_dir, character_name, values)


def load_character_config(
    characters_dir: Path,
    character_name: str,
) -> dict[str, Any]:
    """检查默认分区，迁移角色旧配置，再递归合并并校验。"""
    default_path = characters_dir / DEFAULT_CONFIG_FILENAME
    character_path = characters_dir / character_name / CHARACTER_CONFIG_FILENAME

    config = _read_toml(default_path)
    # 默认文件必须由用户更新，不能用自动迁移掩盖默认配置版本落后。
    if any(not isinstance(config.get(section), dict) for section in ("character", "frontend")):
        raise ValueError(
            f"默认角色配置缺少有效的 [character] 或 [frontend]：{default_path}。"
            "请将 character_config.default.toml 更新到最新版本。"
        )
    config = merge_config(config, _load_character_override(character_path))
    character = config["character"]
    frontend = config["frontend"]

    true_name = character.get("true_character_name")
    if not isinstance(true_name, str):
        raise ValueError("角色配置 character.true_character_name 必须是字符串")
    if not true_name.strip():
        character["true_character_name"] = character_name
    else:
        character["true_character_name"] = true_name.strip()

    scene_mode = character.get("scene_mode")
    if not isinstance(scene_mode, str) or scene_mode not in VALID_SCENE_MODES:
        raise ValueError(
            "角色配置 character.scene_mode 只能是 'realtime' 或 'sandbox'"
        )

    frontend["chat_theme"] = normalize_chat_theme(frontend.get("chat_theme"))
    frontend["favour"] = normalize_favour(frontend.get("favour"))
    frontend["group"] = normalize_character_group(frontend.get("group", ""))

    # 在初始化时检查会共同影响容量清理的两个参数。
    max_capacity = get_int_config(
        config, "memory.retention.max_capacity"
    )
    safe_margin = get_int_config(
        config, "memory.retention.safe_margin", minimum=0
    )
    if max_capacity < 2 * safe_margin:
        raise ValueError(
            "角色配置 memory.retention.max_capacity "
            "必须不少于 safe_margin 的两倍"
        )

    config["display"]["tool_call_content_allowlist"] = (
        get_string_list_config(
            config,
            "display.tool_call_content_allowlist",
        )
    )

    return config
