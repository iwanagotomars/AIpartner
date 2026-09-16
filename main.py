from copy import deepcopy
from pathlib import Path
from threading import Lock, Thread
from time import time
from typing import Literal
from urllib.parse import quote
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr, Field

from utils.manage_character import (
    CharacterManager,
    CharacterRuntime,
    CharacterNotFoundError,
    CharacterNotSelectedError,
)
from utils.manage_generation import (
    GenerationBusyError,
    GenerationCoordinator,
    GenerationJob,
)
from utils.display_state import (
    DisplayQueueEmptyError,
    DisplayQueueOrderError,
)
from utils.chat_history import (
    HistoryCursorError,
    HistoryQueueEmptyError,
    HistoryQueueOrderError,
)
from utils.frontend_assets import (
    ASSET_SPECS,
    BACKGROUND_WHITE_OVERLAY_OPACITY,
    MAX_FRONTEND_IMAGE_BYTES,
    FrontendAssetError,
    FrontendAssetStore,
    FrontendAssetTooLargeError,
)
from utils.portrait_layout import (
    PortraitLayoutError,
    PortraitLayoutStore,
)
from utils.character_config import (
    DEFAULT_CHAT_THEME,
    normalize_chat_theme,
    save_character_chat_theme,
    save_character_favour,
    save_character_group,
    validate_character_group,
)
from utils.character_groups import (
    CharacterGroupRecordError,
    CharacterGroupStore,
)
from utils.character_setting import read_character_setting

from utils.vision import (
    MAX_CHAT_IMAGES, MAX_IMAGE_BYTES, ChatUploadLimit, prepare_chat_images,
    vision_unavailable_reason, split_image_description_with_reply,
)

app = FastAPI()
app.add_middleware(ChatUploadLimit)

BASE_DIR = Path(__file__).resolve().parent
WAV_DIR = BASE_DIR / "wavs"
FRONTEND_DIR = BASE_DIR / "frontend"
WAV_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/wavs", StaticFiles(directory=WAV_DIR), name="wavs")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

character_manager = CharacterManager(BASE_DIR)
character_group_store = CharacterGroupStore(character_manager.characters_dir)
frontend_asset_store = FrontendAssetStore(BASE_DIR)
portrait_layout_store = PortraitLayoutStore()
generation_coordinator = GenerationCoordinator()

# 最后一段语音可能仍在浏览器中播放，新一轮清理时必须保留它。
last_tts_generated: Path | None = None
last_tts_generated_lock = Lock()


class ChatImage(BaseModel):
    data_url: str


# chat函数的输入格式
class ChatRequest(BaseModel):
    message: str
    runtime_id: str
    images: list[ChatImage] = Field(default_factory=list)


# chat函数的输出格式
class ChatResponse(BaseModel):
    session_id: str | None
    user_input: str
    reply: str
    memory_consolidating: bool
    voice_available: bool
    display_enabled: bool
    portrait_url: str | None = None
    image_description: str | None = None


# chat_status函数的输出格式
class ChatStatusResponse(BaseModel):
    memory_consolidating: bool
    memory_consolidation_error: str | None
    display_enabled: bool
    activities: dict[str, bool]
    generation_busy: bool
    display_exist: bool
    ready_display_id: str | None
    ready_history_id: str | None
    turn_id: str | None
    reply_finished: bool
    final_reply: str | None
    turn_error: str | None


class DisplaySettingRequest(BaseModel):
    """修改单个角色演出规划开关时的请求。"""

    enabled: bool
    runtime_id: str


class DisplaySettingResponse(BaseModel):
    """返回后端实际保存的角色演出规划状态。"""

    display_enabled: bool


class DisplayBootstrapResponse(BaseModel):
    """返回旮旯模式首次展示所需的只读信息。"""

    display_enabled: bool
    default_portrait_url: str | None
    vision_enabled: bool = False
    vision_unavailable_reason: str | None = None
    max_chat_images: int = MAX_CHAT_IMAGES
    max_image_bytes: int = MAX_IMAGE_BYTES


class ChatThemeRequest(BaseModel):
    """主题接口只接受运行时标识和白名单主题名。"""

    model_config = ConfigDict(extra="forbid")

    runtime_id: str
    chat_theme: str


class ChatThemeResponse(BaseModel):
    chat_theme: str


class CharacterFavourRequest(BaseModel):
    """喜爱接口只接受一个严格的布尔值。"""

    model_config = ConfigDict(extra="forbid")

    favour: StrictBool


class CharacterFavourResponse(BaseModel):
    favour: bool


class CharacterGroupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group: StrictStr


class CharacterGroupResponse(BaseModel):
    favour: bool
    group: str


class CharacterGroupOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group: StrictStr
    direction: Literal["up", "down"]


class CharacterGroupsResponse(BaseModel):
    groups: list[str]


class CharacterGroupDeleteResponse(BaseModel):
    deleted: bool


class CharacterSummary(BaseModel):
    name: str
    display_name: str
    profile_url: str | None
    favour: bool
    group: str
    scene_mode: str


class CharacterListResponse(BaseModel):
    characters: list[CharacterSummary]


class CharacterSettingResponse(BaseModel):
    content: str


class CharacterSelectResponse(BaseModel):
    character: str
    chat_url: str


class CharacterReleaseResponse(BaseModel):
    released: bool


class FrontendAssetsResponse(BaseModel):
    user_profile_url: str | None
    background_image_gal_url: str | None
    background_overlay_opacity: float


class FrontendAssetUploadResponse(BaseModel):
    asset_type: str
    url: str


class PortraitLayoutRequest(BaseModel):
    """立绘布局接口只接受固定的展示参数。"""

    model_config = ConfigDict(extra="forbid")

    runtime_id: StrictStr
    offset_x_vw: float
    offset_y_vh: float
    scale: float


class PortraitLayoutResponse(BaseModel):
    offset_x_vw: float
    offset_y_vh: float
    scale: float


class GenerationStatusResponse(BaseModel):
    busy: bool
    character: str | None = None
    stage: str | None = None
    started_at: float | None = None


class ChatHistoryPageResponse(BaseModel):
    turns: list[dict]
    has_more: bool
    next_before_turn_id: str | None
    total_turns: int
    history_file_path: str


def require_runtime(
    requested_character: str,
    runtime_id: str | None = None,
) -> CharacterRuntime:
    """把角色管理层异常转换成HTTP响应。"""
    try:
        runtime = character_manager.require_runtime(requested_character)
    except CharacterNotSelectedError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if runtime_id is not None and runtime.runtime_id != runtime_id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "stale_runtime",
                "message": "角色已经被重新初始化，请关闭当前旧窗口后重新打开。",
            },
        )
    return runtime


def generation_busy_response(error: GenerationBusyError) -> HTTPException:
    return HTTPException(
        status_code=423,
        detail={
            "code": "generation_busy",
            "message": str(error),
            "character": error.active_job.character_name,
            "stage": error.active_job.stage,
        },
    )


def initialize_character_runtime(
    selected_character: str,
) -> CharacterRuntime:
    try:
        generation_job = generation_coordinator.try_start(
            selected_character,
            stage="初始化角色",
        )
    except GenerationBusyError as error:
        raise generation_busy_response(error) from error

    try:
        return character_manager.select(
            selected_character,
            force_reload=True,
        )
    except CharacterNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"角色初始化失败：{type(error).__name__}: {error}",
        ) from error
    finally:
        generation_coordinator.finish(generation_job.token)


def release_character_resources(
    character_name: str,
    runtime_id: str,
) -> bool:
    """释放一次角色初始化持有的 Runtime 和 Voice Prompt。"""
    try:
        generation_job = generation_coordinator.try_start(
            character_name,
            stage="关闭角色",
        )
    except GenerationBusyError as error:
        raise generation_busy_response(error) from error

    try:
        runtime = character_manager.release(character_name, runtime_id)
        if runtime is None:
            print(f'[清除角色资源失败] 角色 runtime 资源清除失败！')
            return False

        if runtime.tts_generator is not None:
            runtime.tts_generator.delete_character(character_name)
        print(f'[清除角色资源] 角色 runtime 资源已清除')
        return True
    finally:
        generation_coordinator.finish(generation_job.token)


def get_character_audio_directory(character_name: str) -> Path:
    """返回角色专属 WAV 目录，并确保路径位于 WAV_DIR 内。"""
    audio_directory = (WAV_DIR / character_name).resolve()
    if audio_directory.parent != WAV_DIR.resolve():
        raise ValueError(f"非法角色语音目录：{character_name}")
    return audio_directory


def prepare_character_audio_directory(character_name: str) -> Path:
    """清理角色旧语音，但保留全局最后生成、可能仍在播放的文件。"""
    audio_directory = get_character_audio_directory(character_name)
    audio_directory.mkdir(parents=True, exist_ok=True)

    with last_tts_generated_lock:
        protected_path = last_tts_generated
        for audio_path in audio_directory.glob("*.wav"):
            if protected_path is not None and audio_path.resolve() == protected_path:
                continue
            try:
                audio_path.unlink()
            except OSError as error:
                # 清理失败不应阻断新一轮对话。
                print(f"[清理角色语音失败] {audio_path}: {error}")

    return audio_directory


def remember_last_tts_generated(audio_path: Path) -> None:
    """记录最近一次成功生成的语音文件。"""
    global last_tts_generated
    with last_tts_generated_lock:
        last_tts_generated = audio_path.resolve()


def get_last_ai_reply(messages) -> str:
    """从消息列表中获取最后一条 AI 回复。"""
    for message in reversed(messages):
        if isinstance(message, AIMessage) and message.content:
            return str(message.content)

    return "刚刚似乎出了某种问题，可以重复一下之前的话吗？"


def build_input_state(user_text: str, runtime: CharacterRuntime) -> dict:
    """把浏览器输入写入当前对话 state。"""
    user_message = HumanMessage(content=user_text)

    next_state = deepcopy(runtime.conversation_state)

    # 写入正常的 message 列表
    next_state["messages"] = [
        *next_state.get("messages", []),
        user_message
    ]

    # 写入未保存 message 列表
    next_state["unsaved_messages"] = [
        *next_state.get("unsaved_messages", []),
        user_message
    ]

    next_state["is_quit"] = False
    # 之前有严格的校验机制在，到了这个地方说明记忆归档未进行
    next_state["memory_consolidating"] = False
    next_state["memory_consolidation_error"] = None

    # 更新每轮消息数量
    # updata_num_msg_per_turn_by_accumulation(next_state, 1)

    return next_state


def run_memory_consolidation(
    runtime: CharacterRuntime,
    memory_state: dict,
):
    """
    响应返回浏览器后执行。
    归档结束后解除 memory_consolidating 锁。
    """
    try:
        # 2. 完成归档、总结、保存或压缩
        with runtime.activity_status.running("consolidating_memory"):
            final_state = runtime.memory_graph.invoke(
                memory_state,
                config=runtime.graph_config,
            )

        # 3. 归档结束，解锁聊天框
        final_state["memory_consolidating"] = False
        final_state["memory_consolidation_error"] = None

    except Exception as error:
        # 即使归档失败，也必须解锁输入框
        final_state = memory_state
        final_state["memory_consolidating"] = False
        final_state["memory_consolidation_error"] = (
            f"{type(error).__name__}: {error}"
        )

    with runtime.memory_lock:
        # 因为 memory_consolidating=True 时后端拒绝新输入，
        # 所以此处不会覆盖新的用户消息。
        runtime.conversation_state = final_state


def _natural_display_text(runtime: CharacterRuntime, content: str) -> tuple[str, str]:
    description, reply = split_image_description_with_reply(content)
    if runtime.display_service is not None:
        reply = runtime.display_service.parser_get_natural_text(reply)
    return description, reply.strip()


def _append_text_only_display(
    runtime: CharacterRuntime,
    turn_id: str,
    source: dict,
    error: str | None = None,
) -> None:
    """演出关闭或单条处理失败时仍向前端交付文本。"""
    _, natural_reply = _natural_display_text(runtime, source["content"])
    if not natural_reply:
        return
    display_id = uuid4().hex
    portrait_url = (
        runtime.display_service.default_portrait_url
        if runtime.display_service is not None
        else None
    )
    runtime.display_state.append_display(
        turn_id,
        {
            "id": display_id,
            "turn_id": turn_id,
            "type": "display",
            "source_type": source["type"],
            "content_split": natural_reply,
            "portrait_url": portrait_url,
            "audio_url": None,
            "error": error,
        },
    )


def process_display_queue(
    runtime: CharacterRuntime,
    turn_id: str,
    display_enabled: bool,
) -> None:
    """按 FIFO 解析模型内嵌的演出标记并逐段生成语音。"""
    audio_directory = get_character_audio_directory(runtime.character_name)
    audio_directory.mkdir(parents=True, exist_ok=True)

    try:
        while True:
            source = runtime.display_state.take_unplanned(turn_id)
            if source is None:
                return

            try:
                if (
                    not display_enabled
                    or runtime.display_service is None
                    or runtime.tts_generator is None
                ):
                    _append_text_only_display(runtime, turn_id, source)
                    continue

                with runtime.activity_status.running("planning_display"):
                    plan = runtime.display_service.plan(source["content"])

                display_chunks = plan["reply_chunks"]
                speech_chunks = display_chunks
                speech_language = runtime.source_language
                if runtime.translator is not None:
                    with runtime.activity_status.running(
                        "synthesizing_speech"
                    ):
                        speech_chunks = runtime.translator.translate(
                            display_chunks
                        )
                    speech_language = runtime.target_language

                for chunk, speech_chunk, portrait_url, ref_audio, ref_text in zip(
                    display_chunks,
                    speech_chunks,
                    plan["character_portraits"],
                    plan["character_ref_audios"],
                    plan["character_ref_texts"],
                ):
                    display_id = uuid4().hex
                    filename = f"{turn_id}_{display_id}.wav"
                    output_path = audio_directory / filename
                    audio_url = None
                    tts_error = None

                    try:
                        with runtime.activity_status.running(
                            "synthesizing_speech"
                        ):
                            with runtime.tts_lock:
                                runtime.tts_generator.generate(
                                    ref_audio=ref_audio,
                                    ref_text=ref_text,
                                    gen_text=speech_chunk,
                                    file_wave=str(output_path),
                                    language=speech_language,
                                )
                        remember_last_tts_generated(output_path)
                        audio_url = (
                            f"/wavs/"
                            f"{quote(runtime.character_name, safe='')}/"
                            f"{quote(filename, safe='')}"
                        )
                    except Exception as error:
                        # 单段语音失败不应中断后续文本和演出。
                        tts_error = f"语音合成失败：{error}"

                    runtime.display_state.append_display(
                        turn_id,
                        {
                            "id": display_id,
                            "turn_id": turn_id,
                            "type": "display",
                            "source_type": source["type"],
                            "content_split": chunk,
                            "portrait_url": portrait_url,
                            "audio_url": audio_url,
                            "error": tts_error,
                        },
                    )
            except Exception as error:
                # 演出规划或翻译失败时降级为自然文本，避免整条回复消失。
                _append_text_only_display(
                    runtime,
                    turn_id,
                    source,
                    error=f"演出处理失败：{error}",
                )
            finally:
                runtime.display_state.complete_unplanned(turn_id)
    except Exception as error:
        runtime.display_state.set_turn_error(
            turn_id,
            f"演出工作线程异常：{type(error).__name__}: {error}",
        )
    finally:
        runtime.display_state.mark_worker_finished(turn_id)


def complete_reply_in_background(
    runtime: CharacterRuntime,
    turn_id: str,
    memory_state: dict,
    generation_job: GenerationJob,
) -> None:
    """等待演出生产完成，再整理记忆并释放全局生成权。"""
    try:
        generation_coordinator.update_stage(
            generation_job.token,
            "生成分段语音",
        )
        runtime.display_state.wait_until_worker_finished(turn_id)

        generation_coordinator.update_stage(
            generation_job.token,
            "整理角色记忆",
        )
        run_memory_consolidation(runtime, memory_state)
    finally:
        generation_coordinator.finish(generation_job.token)


# 返回聊天页面
@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(
        FRONTEND_DIR / "favicon.ico",
        media_type="image/x-icon",
    )


@app.get("/", include_in_schema=False)
def read_index():
    # 选择页会生成加载窗口，必须同时更新 HTML 与其引用的前端资源。
    return FileResponse(
        FRONTEND_DIR / "index.html",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/characters", response_model=CharacterListResponse)
def list_characters():
    """返回角色轻量信息；喜爱角色优先且保留原有系统顺序。"""
    characters = []
    for character in character_manager.list_characters():
        config = character_manager.load_character_config(character.name)
        characters.append(
            CharacterSummary(
                name=character.name,
                display_name=config["character"]["true_character_name"],
                profile_url=(
                    f"/api/characters/{quote(character.name, safe='')}/profile"
                    if character.profile_path is not None
                    else None
                ),
                favour=config["frontend"]["favour"],
                group=config["frontend"]["group"],
                scene_mode=config["character"]["scene_mode"],
            )
        )

    characters.sort(key=lambda character: not character.favour)
    return CharacterListResponse(characters=characters)


@app.get(
    "/api/characters/{requested_character}/character-setting",
    response_model=CharacterSettingResponse,
)
def read_character_setting_for_selection(requested_character: str):
    """按需读取选择页展示的完整角色设定，不初始化角色运行时。"""
    try:
        character = character_manager.get_character(requested_character)
        content = read_character_setting(character.directory, character.name)
    except CharacterNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except UnicodeError as error:
        raise HTTPException(
            status_code=500,
            detail="角色设定文件不是有效的 UTF-8 文本。",
        ) from error
    except ValueError:
        content = ""
    except OSError as error:
        raise HTTPException(
            status_code=500,
            detail="角色设定文件读取失败。",
        ) from error

    return CharacterSettingResponse(
        content=(
            content
            or "未找到角色设定文件，请检查相应角色文件夹。"
        )
    )


@app.put(
    "/api/characters/{requested_character}/favour",
    response_model=CharacterFavourResponse,
)
def update_character_favour(
    requested_character: str,
    request: CharacterFavourRequest,
):
    """保存选择页喜爱状态，不创建或修改角色对话运行时。"""
    try:
        character = character_manager.get_character(requested_character)
        save_character_favour(
            character_manager.characters_dir,
            character.name,
            request.favour,
        )
    except CharacterNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(
            status_code=500,
            detail="角色喜爱状态保存失败，原有配置未被修改。",
        ) from error

    return CharacterFavourResponse(favour=request.favour)


def get_referenced_character_groups() -> list[str]:
    """按系统角色顺序收集当前非空自定义分组。"""
    groups = []
    for character in character_manager.list_characters():
        group = character_manager.load_character_config(character.name)["frontend"]["group"]
        if group and group not in groups:
            groups.append(group)
    return groups


@app.get(
    "/api/character-groups",
    response_model=CharacterGroupsResponse,
)
def list_character_groups():
    try:
        groups = character_group_store.reconcile(
            get_referenced_character_groups()
        )
    except CharacterGroupRecordError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(
            status_code=500,
            detail="分组顺序保存失败。",
        ) from error
    return CharacterGroupsResponse(groups=groups)


@app.put(
    "/api/character-groups/order",
    response_model=CharacterGroupsResponse,
)
def move_character_group(request: CharacterGroupOrderRequest):
    try:
        groups = character_group_store.move(
            request.group,
            request.direction,
            get_referenced_character_groups(),
        )
    except CharacterGroupRecordError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(
            status_code=500,
            detail="分组顺序保存失败。",
        ) from error
    return CharacterGroupsResponse(groups=groups)


@app.delete(
    "/api/character-groups",
    response_model=CharacterGroupDeleteResponse,
)
def delete_character_group(request: CharacterGroupRequest):
    members = []
    try:
        group = validate_character_group(
            request.group,
            allow_empty=False,
        )
        for character in character_manager.list_characters():
            config = character_manager.load_character_config(character.name)
            if config["frontend"]["group"] == group:
                members.append(character)
        if not members:
            raise ValueError(f"分组 '{group}' 不存在")
        for character in members:
            # 删除分组不取消喜爱；喜爱角色仍保留在虚拟喜爱分组。
            save_character_group(
                character_manager.characters_dir,
                character.name,
                "",
            )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(
            status_code=500,
            detail="删除分组失败，请重试。",
        ) from error
    return CharacterGroupDeleteResponse(deleted=True)


@app.put(
    "/api/characters/{requested_character}/group",
    response_model=CharacterGroupResponse,
)
def update_character_group(
    requested_character: str,
    request: CharacterGroupRequest,
):
    try:
        character = character_manager.get_character(requested_character)
        group = request.group.strip()
        save_character_group(
            character_manager.characters_dir,
            character.name,
            group,
            clear_favour=not group,
        )
        config = character_manager.load_character_config(character.name)
    except CharacterNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(
            status_code=500,
            detail="角色分组保存失败，原有配置未被修改。",
        ) from error
    return CharacterGroupResponse(
        favour=config["frontend"]["favour"],
        group=config["frontend"]["group"],
    )


@app.get("/api/characters/{requested_character}/profile", include_in_schema=False)
def read_character_profile(requested_character: str):
    try:
        profile_path = character_manager.get_character(
            requested_character
        ).profile_path
    except CharacterNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if profile_path is None:
        raise HTTPException(status_code=404, detail="角色头像不存在。")
    return FileResponse(profile_path)


@app.get(
    "/api/characters/{requested_character}/user-profile",
    include_in_schema=False,
)
def read_user_profile(requested_character: str):
    """兼容旧前端地址，返回新的前端资源存储中的用户头像。"""
    try:
        character = character_manager.get_character(requested_character)
        profile_path = frontend_asset_store.resolve(
            character.directory,
            "user_profile",
        )
    except CharacterNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if profile_path is None:
        raise HTTPException(status_code=404, detail="用户头像不存在。")
    return FileResponse(profile_path)


def frontend_asset_url(
    character_name: str,
    asset_type: str,
    path: Path | None,
) -> str | None:
    if path is None:
        return None
    return (
        f"/api/characters/{quote(character_name, safe='')}"
        f"/frontend-assets/{asset_type}?v={path.stat().st_mtime_ns}"
    )


@app.get(
    "/api/characters/{requested_character}/frontend-assets",
    response_model=FrontendAssetsResponse,
)
def read_frontend_assets(requested_character: str):
    """返回当前角色的前端图片URL和背景遮罩配置。"""
    try:
        character = character_manager.get_character(requested_character)
    except CharacterNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    resolved = {
        asset_type: frontend_asset_store.resolve(
            character.directory,
            asset_type,
        )
        for asset_type in ASSET_SPECS
    }
    return FrontendAssetsResponse(
        user_profile_url=frontend_asset_url(
            character.name,
            "user_profile",
            resolved["user_profile"],
        ),
        background_image_gal_url=frontend_asset_url(
            character.name,
            "background_image_gal",
            resolved["background_image_gal"],
        ),
        background_overlay_opacity=BACKGROUND_WHITE_OVERLAY_OPACITY,
    )


@app.get(
    "/api/characters/{requested_character}/frontend-assets/{asset_type}",
    include_in_schema=False,
)
def read_frontend_asset(requested_character: str, asset_type: str):
    try:
        character = character_manager.get_character(requested_character)
        path = frontend_asset_store.resolve(character.directory, asset_type)
    except (CharacterNotFoundError, FrontendAssetError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if path is None:
        raise HTTPException(status_code=404, detail="前端图片不存在。")
    return FileResponse(path, headers={"Cache-Control": "no-store"})


@app.put(
    "/api/characters/{requested_character}/frontend-assets/{asset_type}",
    response_model=FrontendAssetUploadResponse,
)
async def upload_frontend_asset(
    requested_character: str,
    asset_type: str,
    runtime_id: str,
    request: Request,
):
    """保存用户选择的角色前端图片；失败时保留已有资源。"""
    runtime = require_runtime(requested_character, runtime_id)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_FRONTEND_IMAGE_BYTES:
                raise HTTPException(status_code=413, detail="图片不能超过 15 MB。")
        except ValueError:
            pass

    try:
        path = frontend_asset_store.save(
            character_manager.get_character(requested_character).directory,
            asset_type,
            await request.body(),
        )
    except FrontendAssetTooLargeError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except FrontendAssetError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(
            status_code=500,
            detail="图片保存失败，原有资源未被修改。",
        ) from error

    return FrontendAssetUploadResponse(
        asset_type=asset_type,
        url=frontend_asset_url(runtime.character_name, asset_type, path),
    )


@app.get(
    "/api/characters/{requested_character}/portrait-layout",
    response_model=PortraitLayoutResponse,
)
def read_portrait_layout(requested_character: str, runtime_id: str):
    """读取当前角色所有立绘共用的页面布局。"""
    require_runtime(requested_character, runtime_id)
    try:
        character = character_manager.get_character(requested_character)
    except CharacterNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return PortraitLayoutResponse(
        **portrait_layout_store.load(character.directory)
    )


@app.put(
    "/api/characters/{requested_character}/portrait-layout",
    response_model=PortraitLayoutResponse,
)
def update_portrait_layout(
    requested_character: str,
    request: PortraitLayoutRequest,
):
    """保存前端立绘布局，不修改角色对话或演出运行状态。"""
    require_runtime(requested_character, request.runtime_id)
    try:
        character = character_manager.get_character(requested_character)
        layout = portrait_layout_store.save(
            character.directory,
            {
                "offset_x_vw": request.offset_x_vw,
                "offset_y_vh": request.offset_y_vh,
                "scale": request.scale,
            },
        )
    except CharacterNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PortraitLayoutError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(
            status_code=500,
            detail="立绘布局保存失败，原有配置未被修改。",
        ) from error
    return PortraitLayoutResponse(**layout)


@app.post(
    "/api/characters/{requested_character}/select",
    response_model=CharacterSelectResponse,
)
def select_character(requested_character: str):
    """重新读取角色资源并初始化独立运行时。"""
    runtime = initialize_character_runtime(requested_character)
    return CharacterSelectResponse(
        character=requested_character,
        chat_url=(
            f"/chat/{quote(requested_character, safe='')}"
            f"?runtime_id={runtime.runtime_id}"
            f"&display_name={quote(runtime.true_character_name, safe='')}"
        ),
    )


@app.delete(
    "/api/characters/{requested_character}/runtimes/{runtime_id}",
    response_model=CharacterReleaseResponse,
)
def release_character(requested_character: str, runtime_id: str):
    """关闭角色窗口时释放本次初始化所持有的角色资源。"""
    return CharacterReleaseResponse(
        released=release_character_resources(
            requested_character,
            runtime_id,
        )
    )


@app.get("/chat/{requested_character}", include_in_schema=False)
def read_chat_page(requested_character: str, runtime_id: str):
    require_runtime(requested_character, runtime_id)
    return FileResponse(FRONTEND_DIR / "chat.html")


@app.get(
    "/api/characters/{requested_character}/portraits/{filename}",
    include_in_schema=False,
)
def read_portrait(requested_character: str, filename: str):
    """只公开指定已初始化角色 portraits 目录中的图片文件。"""
    try:
        return FileResponse(
            character_manager.get_portrait_path(
                requested_character,
                filename,
            )
        )
    except CharacterNotSelectedError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="立绘不存在。") from error


@app.get("/api/generation-status", response_model=GenerationStatusResponse)
def generation_status():
    active_job = generation_coordinator.status()
    if active_job is None:
        return GenerationStatusResponse(busy=False)
    return GenerationStatusResponse(
        busy=True,
        character=active_job.character_name,
        stage=active_job.stage,
        started_at=active_job.started_at,
    )


# 查询记忆是否仍在归档
@app.get(
    "/api/characters/{requested_character}/status",
    response_model=ChatStatusResponse,
)
def chat_status(requested_character: str, runtime_id: str):
    """返回角色活动状态；展示用快照无需等待对话主锁。"""
    runtime = require_runtime(requested_character, runtime_id)
    display_snapshot = runtime.display_state.snapshot()
    active_generation = generation_coordinator.status()
    history_snapshot = (
        runtime.history_store.snapshot()
        if runtime.history_store is not None
        else {"ready_history_id": None}
    )
    return ChatStatusResponse(
        memory_consolidating=runtime.conversation_state.get(
            "memory_consolidating",
            False
        ),
        memory_consolidation_error=runtime.conversation_state.get(
            "memory_consolidation_error"
        ),
        display_enabled=runtime.display_enabled,
        activities=runtime.activity_status.snapshot(),
        generation_busy=active_generation is not None,
        **history_snapshot,
        **display_snapshot,
    )


@app.get(
    "/api/characters/{requested_character}/history",
    response_model=ChatHistoryPageResponse,
)
def get_chat_history(
    requested_character: str,
    runtime_id: str,
    limit: int = 10,
    before_turn_id: str | None = None,
):
    """按轮次分页读取只服务于前端展示的对话历史。"""
    runtime = require_runtime(requested_character, runtime_id)
    if not 1 <= limit <= 10:
        raise HTTPException(status_code=400, detail="limit 必须在 1 到 10 之间。")
    if runtime.history_store is None:
        raise HTTPException(status_code=503, detail="对话历史服务不可用。")
    try:
        return runtime.history_store.get_turns(limit, before_turn_id)
    except HistoryCursorError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get(
    "/api/characters/{requested_character}/history/events/{event_id}"
)
def get_ready_history_event(
    requested_character: str,
    event_id: str,
    runtime_id: str,
):
    """按 ID 领取实时历史 FIFO 队首。"""
    runtime = require_runtime(requested_character, runtime_id)
    if runtime.history_store is None:
        raise HTTPException(status_code=503, detail="对话历史服务不可用。")
    try:
        return runtime.history_store.pop_ready_event(event_id)
    except HistoryQueueEmptyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except HistoryQueueOrderError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/characters/{requested_character}/history/images/{filename}")
def get_history_image(requested_character: str, filename: str, runtime_id: str):
    """沿用当前运行环境的历史目录，隔离普通与沙盒记忆。"""
    runtime = require_runtime(requested_character, runtime_id)
    if runtime.history_store is None:
        raise HTTPException(status_code=404, detail="历史图片不存在。")
    try:
        path = runtime.history_store.image_path(filename)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="历史图片不存在。") from error
    if not path.is_file():
        raise HTTPException(status_code=404, detail="历史图片不存在。")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get(
    "/api/characters/{requested_character}/displays/{display_id}"
)
def get_ready_display(
    requested_character: str,
    display_id: str,
    runtime_id: str,
):
    """按 ID 领取当前角色 display_queue 的 FIFO 队首。"""
    runtime = require_runtime(requested_character, runtime_id)
    try:
        return runtime.display_state.pop_ready_display(display_id)
    except DisplayQueueEmptyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except DisplayQueueOrderError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "display_not_ready",
                "message": str(error),
            },
        ) from error


@app.get(
    "/api/characters/{requested_character}/chat-theme",
    response_model=ChatThemeResponse,
)
def read_chat_theme(requested_character: str, runtime_id: str):
    runtime = require_runtime(requested_character, runtime_id)
    return ChatThemeResponse(
        chat_theme=normalize_chat_theme(
            runtime.character_config["frontend"].get("chat_theme", DEFAULT_CHAT_THEME)
        )
    )


@app.put(
    "/api/characters/{requested_character}/chat-theme",
    response_model=ChatThemeResponse,
)
def update_chat_theme(
    requested_character: str,
    request: ChatThemeRequest,
):
    """独立保存视觉主题，不占用或修改角色对话运行状态。"""
    runtime = require_runtime(requested_character, request.runtime_id)
    try:
        save_character_chat_theme(
            character_manager.characters_dir,
            runtime.character_name,
            request.chat_theme,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(
            status_code=500,
            detail="聊天主题保存失败，原有配置未被修改。",
        ) from error

    runtime.character_config["frontend"]["chat_theme"] = request.chat_theme
    return ChatThemeResponse(chat_theme=request.chat_theme)


@app.get(
    "/api/characters/{requested_character}/display/bootstrap",
    response_model=DisplayBootstrapResponse,
)
def read_display_bootstrap(requested_character: str, runtime_id: str):
    """返回旮旯模式初始化信息，不修改运行状态或演出队列。"""
    runtime = require_runtime(requested_character, runtime_id)
    display_service = runtime.display_service
    reason = vision_unavailable_reason(runtime.character_config)
    return DisplayBootstrapResponse(
        vision_enabled=reason is None,
        vision_unavailable_reason=reason,
        display_enabled=runtime.display_enabled,
        default_portrait_url=(
            display_service.default_portrait_url
            if runtime.display_enabled and display_service is not None
            else None
        ),
    )


@app.put(
    "/api/characters/{requested_character}/display",
    response_model=DisplaySettingResponse,
)
def update_display_setting(
    requested_character: str,
    request: DisplaySettingRequest,
):
    """在全局生成器空闲时修改指定角色的演出规划开关。"""
    runtime = require_runtime(requested_character, request.runtime_id)
    try:
        generation_job = generation_coordinator.try_start(
            requested_character,
            stage="更新演出设置",
        )
    except GenerationBusyError as error:
        raise generation_busy_response(error) from error

    try:
        with runtime.memory_lock:
            if request.enabled and runtime.display_unavailable_reason:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "演出规划当前不可用："
                        f"{runtime.display_unavailable_reason}。"
                        "请补全或修复资源后返回角色选择页重新初始化。"
                    ),
                )
            runtime.display_enabled = request.enabled
            return DisplaySettingResponse(
                display_enabled=runtime.display_enabled
            )
    finally:
        generation_coordinator.finish(generation_job.token)


# 发送用户消息并获取 AI 回复
@app.post(
    "/api/characters/{requested_character}/chat",
    response_model=ChatResponse,
)
def chat(
    requested_character: str,
    request: ChatRequest,
    background_tasks: BackgroundTasks
):
    runtime = require_runtime(requested_character, request.runtime_id)
    user_text = request.message.strip()

    has_images = bool(request.images)
    if has_images and (reason := vision_unavailable_reason(runtime.character_config)):
        raise HTTPException(status_code=400, detail=reason)
    if not user_text and not has_images:
        raise HTTPException(
            status_code=400,
            detail="输入内容不能为空。"
        )

    try:
        generation_job = generation_coordinator.try_start(
            requested_character,
            stage="生成文本回复",
        )
    except GenerationBusyError as error:
        raise generation_busy_response(error) from error

    vision_turn = None
    handed_to_background = False
    turn_started = False
    history_started = False
    reply_succeeded = False
    turn_id = uuid4().hex
    started_at = time()
    history_store = runtime.history_store
    try:
        with runtime.memory_lock:
            consolidation_error = runtime.conversation_state.get(
                "memory_consolidation_error"
            )
            if (
                isinstance(consolidation_error, str)
                and consolidation_error.startswith(
                    "MessageStateValidationError:"
                )
            ):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "message_state_invalid",
                        "message": consolidation_error,
                    },
                )

            # 即使绕过前端，也不能在当前角色记忆归档期间插入消息。
            if runtime.conversation_state.get("memory_consolidating", False):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "memory_consolidating",
                        "message": "记忆正在归档，请稍后再发送。",
                    },
                )

            if runtime.display_state.snapshot()["display_exist"]:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "display_pending",
                        "message": "上一轮演出尚未领取完成，请稍后再发送。",
                    },
                )

            if has_images:
                try:
                    images = prepare_chat_images([item.data_url for item in request.images[:MAX_CHAT_IMAGES]])
                except ValueError as error:
                    raise HTTPException(status_code=400, detail=str(error)) from error
                user_text = (user_text + "\n" if user_text else "") + f"[用户发送了{len(images)}张图片]"
                vision_turn = {"images": images, "description": "", "description_published": False}

            if history_store is not None:
                try:
                    history_store.start_turn(
                        turn_id=turn_id,
                        user_text=user_text,
                        speaker="User",
                        created_at=started_at,
                        image_data_urls=[item.data_url for item in request.images[:MAX_CHAT_IMAGES]],
                    )
                    history_started = True
                except Exception as error:
                    # 历史功能异常不能阻断主对话。
                    print(
                        "[对话历史写入失败] "
                        f"{type(error).__name__}: {error}"
                    )
                    history_store = None

            request.images.clear()  # 存档完成后释放原图；Base64 不进入历史 JSON。
            prepare_character_audio_directory(runtime.character_name)
            input_state = build_input_state(user_text, runtime)

            # 固定本轮演出开关，并让对话图能把每次 AI 文本写入队列。
            display_enabled = runtime.display_enabled
            configurable = runtime.graph_config.setdefault("configurable", {})
            configurable.update({
                "display_enabled": display_enabled,
                "display_service": runtime.display_service,
                "display_state": runtime.display_state,
                "history_store": history_store,
                "turn_id": turn_id,
            })

            configurable["vision_turn"] = vision_turn
            runtime.display_state.start_turn(turn_id)
            turn_started = True
            Thread(
                target=process_display_queue,
                args=(runtime, turn_id, display_enabled),
                name=f"display-{runtime.character_name}-{turn_id[:8]}",
                daemon=True,
            ).start()

            with runtime.activity_status.running("generating_reply"):
                reply_state = runtime.reply_graph.invoke(
                    input_state,
                    config=runtime.graph_config,
                )

            raw_reply = get_last_ai_reply(reply_state["messages"])
            description, reply = _natural_display_text(runtime, raw_reply)
            image_description = None
            if vision_turn is not None:
                image_description = vision_turn["description"] or description
            reply_succeeded = True

            # 测试替身或外部 ReplyGraph 可能绕过 agent_node，确保最终回复不丢失。
            if not runtime.display_state.reply_finished(turn_id):
                runtime.display_state.enqueue_unplanned(
                    turn_id,
                    "reply_directly",
                    split_image_description_with_reply(raw_reply)[1],
                )
                runtime.display_state.set_final_reply(turn_id, reply)
            runtime.display_state.finish_input(turn_id)

            if history_store is not None:
                try:
                    if vision_turn is not None and not vision_turn["description_published"]:
                        history_store.append_event(
                            turn_id, "vision_description", "assistant", runtime.true_character_name,
                            image_description or "未提取到独立的图片识别描述，请参考下方回复。", time(),
                        )
                    history_store.complete_turn(
                        turn_id=turn_id,
                        speaker=runtime.true_character_name,
                        content=reply,
                        completed_at=time(),
                    )
                except Exception as error:
                    print(
                        "[对话历史写入失败] "
                        f"{type(error).__name__}: {error}"
                    )

            memory_state = deepcopy(reply_state)
            memory_state["memory_consolidating"] = True
            memory_state["memory_consolidation_error"] = None

            portrait_url = None
            if not display_enabled and runtime.display_service is not None:
                portrait_url = runtime.display_service.default_portrait_url

            # 响应返回后仍保持当前角色和全局生成状态锁定。
            runtime.conversation_state = memory_state

        background_tasks.add_task(
            complete_reply_in_background,
            runtime,
            turn_id,
            memory_state,
            generation_job,
        )
        handed_to_background = True

        return ChatResponse(
            session_id=None,
            user_input=user_text,
            image_description=image_description,
            reply=reply,
            memory_consolidating=True,
            voice_available=(
                display_enabled and runtime.tts_generator is not None
            ),
            display_enabled=display_enabled,
            portrait_url=portrait_url,
        )
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"AI 回复生成失败：{error}",
        ) from error
    finally:
        if vision_turn is not None:
            vision_turn.pop("images", None)
        runtime.graph_config.get("configurable", {}).pop("vision_turn", None)
        request.images.clear()
        if not handed_to_background:
            if history_started and not reply_succeeded:
                try:
                    runtime.history_store.fail_turn(turn_id, time())
                except Exception as error:
                    print(
                        "[对话历史状态写入失败] "
                        f"{type(error).__name__}: {error}"
                    )
            if turn_started:
                runtime.display_state.finish_input(turn_id)
                runtime.display_state.wait_until_worker_finished(turn_id)
            generation_coordinator.finish(generation_job.token)
