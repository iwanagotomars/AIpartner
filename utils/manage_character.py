from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from chatGUI import create_runtime

from .character_config import (
    get_memory_root,
    load_character_config,
    normalize_translation_language,
)
from .chat_history import ChatHistoryStore
from .display import CharacterDisplayService
from .display_state import CharacterDisplayState
from .runtime_status import CharacterActivityStatus
from .translation_for_tts import DialogueTranslatorForTTS


PROFILE_SUFFIX_PRIORITY = {".png": 0, ".jpg": 1, ".jpeg": 2}
PORTRAIT_SUFFIXES = {".jpg", ".jpeg", ".png"}


class CharacterNotFoundError(ValueError):
    pass


class CharacterNotSelectedError(RuntimeError):
    pass


@dataclass(frozen=True)
class CharacterOption:
    """选择页面需要的轻量角色信息。"""

    name: str
    directory: Path
    profile_path: Path | None


@dataclass
class CharacterRuntime:
    """一个角色独立的对话、记忆和演出状态。"""

    character_name: str
    reply_graph: Any
    memory_graph: Any
    conversation_state: dict
    graph_config: dict
    tts_generator: Any
    display_service: CharacterDisplayService | None
    portrait_dir: Path
    source_language: str = "Chinese"
    target_language: str = ""
    translator: DialogueTranslatorForTTS | None = None
    history_store: ChatHistoryStore | None = None
    display_state: CharacterDisplayState = field(
        default_factory=CharacterDisplayState
    )
    character_config: dict[str, Any] = field(default_factory=dict)
    activity_status: CharacterActivityStatus = field(
        default_factory=CharacterActivityStatus
    )
    # 标识本次初始化，避免旧窗口关闭时误删重新初始化后的运行时。
    runtime_id: str = field(default_factory=lambda: uuid4().hex)
    # 是否启用立绘规划和语音合成；每个角色独立保存该设置。
    display_enabled: bool = True
    # 演出资源初始化失败时记录原因；非空表示只能进行文本交流。
    display_unavailable_reason: str | None = None
    memory_lock: Lock = field(default_factory=Lock)
    tts_lock: Lock = field(default_factory=Lock)

    @property
    def true_character_name(self) -> str:
        """返回面向用户和大模型显示的角色名称。"""
        name = self.character_config["character"].get("true_character_name", "")
        if isinstance(name, str) and name.strip():
            return name.strip()
        return self.character_name

    @property
    def scene_mode(self) -> str:
        return self.character_config["character"].get("scene_mode", "realtime")


class CharacterManager:
    """负责角色发现以及多个角色运行时的初始化和查找。"""

    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        self.characters_dir = self.project_root / "characters"
        self._characters = self._scan_characters()
        self._runtimes: dict[str, CharacterRuntime] = {}
        self._initialization_lock = Lock()

    def _scan_characters(self) -> dict[str, CharacterOption]:
        if not self.characters_dir.is_dir():
            return {}

        characters: dict[str, CharacterOption] = {}
        character_dirs = sorted(
            (
                path
                for path in self.characters_dir.iterdir()
                if path.is_dir()
            ),
            key=lambda path: path.name.casefold(),
        )
        for character_dir in character_dirs:
            # 如果有多个头像图片，则按照以下顺序排列：PNG > JPG > JPEG
            profiles = sorted(
                (
                    path
                    for path in character_dir.iterdir()
                    if path.is_file()
                    and path.stem.casefold() == "profile"
                    and path.suffix.casefold() in PROFILE_SUFFIX_PRIORITY
                ),
                key=lambda path: (
                    PROFILE_SUFFIX_PRIORITY[path.suffix.casefold()],
                    path.name.casefold(),
                ),
            )
            if len(profiles) > 1:
                print(
                    f"[角色头像警告] {character_dir.name} 存在多个 profile 图片，"
                    f"将使用 {profiles[0].name}。"
                )

            characters[character_dir.name] = CharacterOption(
                name=character_dir.name,
                directory=character_dir,
                profile_path=profiles[0] if profiles else None,
            )
        return characters

    def list_characters(self) -> list[CharacterOption]:
        return list(self._characters.values())

    def get_character(self, character_name: str) -> CharacterOption:
        character = self._characters.get(character_name)
        if character is None:
            raise CharacterNotFoundError(f"角色 '{character_name}' 不存在。")
        return character

    def get_user_profile_path(self, character_name: str) -> Path | None:
        """优先返回角色专属用户头像，否则返回全局用户头像。"""
        character = self.get_character(character_name)
        for directory in (
            character.directory / "frontend_imgs",
            self.project_root / "frontend" / "imgs",
        ):
            if not directory.is_dir():
                continue
            profiles = sorted(
                (
                    path
                    for path in directory.iterdir()
                    if path.is_file()
                    and path.stem.casefold() == "user_profile"
                    and path.suffix.casefold() in PROFILE_SUFFIX_PRIORITY
                ),
                key=lambda path: (
                    PROFILE_SUFFIX_PRIORITY[path.suffix.casefold()],
                    path.name.casefold(),
                ),
            )
            if profiles:
                return profiles[0]
        return None

    def load_character_config(self, character_name: str) -> dict[str, Any]:
        """读取角色最新配置；角色选择页和初始化过程共用此入口。"""
        character = self.get_character(character_name)
        return load_character_config(self.characters_dir, character.name)

    def has_runtime(self, character_name: str) -> bool:
        with self._initialization_lock:
            return character_name in self._runtimes

    def select(
        self,
        character_name: str,
        force_reload: bool = False,
    ) -> CharacterRuntime:
        """初始化角色；force_reload=True 时原子重建角色运行时。"""
        character = self.get_character(character_name)

        with self._initialization_lock:
            runtime = self._runtimes.get(character_name)
            if runtime is not None and not force_reload:
                return runtime

            character_config = self.load_character_config(character.name)
            translate_config = character_config.get("translate", {})
            if not isinstance(translate_config, dict):
                raise ValueError("角色配置 translate 必须是 TOML 区域")
            source_language = normalize_translation_language(
                translate_config.get("source_language", "Chinese"),
                "translate.source_language",
            )
            target_language = normalize_translation_language(
                translate_config.get("target_language", ""),
                "translate.target_language",
                allow_empty=True,
            )
            translate_config["source_language"] = source_language
            translate_config["target_language"] = target_language
            character_config["translate"] = translate_config
            translator = None
            if target_language and target_language != source_language:
                translator = DialogueTranslatorForTTS(
                    source_language=source_language,
                    target_language=target_language,
                    character_dir=character.directory,
                )

            activity_status = CharacterActivityStatus()
            (
                reply_graph,
                memory_graph,
                conversation_state,
                graph_config,
                tts_generator,
                initialized_name,
            ) = create_runtime(
                character_name,
                activity_status=activity_status,
                character_config=character_config,
            )

            display_errors: list[str] = []
            if tts_generator is None:
                display_errors.append("语音模型初始化失败或不可用")

            display_service = None
            try:
                display_service = CharacterDisplayService(
                    project_root=self.project_root,
                    character_name=initialized_name,
                    true_character_name=character_config["character"]["true_character_name"]
                )
            except Exception as error:
                display_errors.append(
                    "立绘或参考音频资源初始化失败："
                    f"{type(error).__name__}: {error}"
                )
            # 更新display_service，便于后续的agent_node进行display
            configurable = graph_config.setdefault("configurable", {})
            configurable["display_service"] = display_service
            display_state = CharacterDisplayState()
            configurable["display_state"] = display_state
            history_store = ChatHistoryStore(
                get_memory_root(character.directory, character_config["character"]["scene_mode"])
            )
            configurable["history_store"] = history_store

            display_unavailable_reason = (
                "；".join(display_errors) if display_errors else None
            )
            if display_unavailable_reason:
                print(
                    f"[角色初始化警告] {initialized_name} 将只启用文本交流："
                    f"{display_unavailable_reason}"
                )

            new_runtime = CharacterRuntime(
                character_name=initialized_name,  # 角色名称
                reply_graph=reply_graph,          # 应答功能的langgraph图
                memory_graph=memory_graph,        # 记忆功能的langgraph图
                conversation_state=conversation_state,  # langgraph图的state
                graph_config=graph_config,              # langgraph图的runnable
                tts_generator=tts_generator,            # 共享Qwen3-TTS生成器
                display_service=display_service,        # 演出规划器
                portrait_dir=(character.directory / "portraits").resolve(),
                source_language=source_language,
                target_language=target_language,
                translator=translator,
                history_store=history_store,
                display_state=display_state,
                character_config=character_config,
                activity_status=activity_status,
                display_enabled=display_unavailable_reason is None,
                display_unavailable_reason=display_unavailable_reason,
            )
            # 新运行时全部构建完成后再替换，失败时保留已有运行时。
            self._runtimes[initialized_name] = new_runtime
            return new_runtime

    def require_runtime(
        self,
        requested_character: str,
    ) -> CharacterRuntime:
        runtime = self._runtimes.get(requested_character)
        if runtime is None:
            raise CharacterNotSelectedError(
                f"角色 '{requested_character}' 尚未初始化，请先在角色选择页打开。"
            )
        return runtime

    def release(
        self,
        character_name: str,
        runtime_id: str,
    ) -> CharacterRuntime | None:
        """仅释放与 runtime_id 匹配的当前角色运行时。"""
        with self._initialization_lock:
            runtime = self._runtimes.get(character_name)
            if runtime is None or runtime.runtime_id != runtime_id:
                return None
            return self._runtimes.pop(character_name)

    def get_portrait_path(
        self,
        character_name: str,
        filename: str,
    ) -> Path:
        """安全解析指定角色的立绘路径，防止跨目录访问。"""
        runtime = self.require_runtime(character_name)
        portrait_path = (runtime.portrait_dir / filename).resolve()
        if (
            portrait_path.parent != runtime.portrait_dir
            or portrait_path.suffix.casefold() not in PORTRAIT_SUFFIXES
            or not portrait_path.is_file()
        ):
            raise FileNotFoundError(filename)
        return portrait_path
