from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from contextlib import nullcontext
from utils.long_memory.long_memory_initializer import generate_long_memory

from utils.memory_utils import (
    MemoryExtraction,
    process_and_archive_memories,
    format_working_memory_for_prompt,
    initialize_core_biography,
    update_working_memory_cache,
    format_timestamp,
    truncate_messages,
    RecentMemoryManager,
    get_previous_turns,
    update_num_msg_per_turn,
)
from utils.memory_db import (
    MemoryManager,
    build_search_tool_for_character,
    get_embedding_function,
)

from utils.web_search import (
    build_web_search_tool,
    initialize_web_search
)

from utils.llm import get_llm, get_thinking_llm, get_vision_llm
from utils.vision import split_image_description_with_reply
from utils.prompt_container import VISION_PROMPT

from utils.character_setting import (
    read_character_setting,
    summary_character_setting
)
from utils.character_config import (
    get_int_config,
    get_memory_root,
    get_string_list_config,
    load_character_config,
)
from utils.prompt_container import PARTNER_SYSTEM_PROMPTS, DISPLAY_PROMPT
from utils.runtime_status import CharacterActivityStatus

from typing import Annotated, TypedDict, Dict
from pathlib import Path
from threading import Lock
import time
import datetime


# ===========================
# 1. 全局配置与资源声明
# ===========================
NUM_CHATS_TO_SAVE = 1  # 对话存储频率
NUM_CHATS_TO_CLEAN_MEMORY = 5  # 记忆库清洗频率
NUM_CHATS_TO_UPDATE_BIO = 50  # 人物传记更新频率
# 保存对话到数据库时忽略的工具调用及其原始输出。
# 记忆检索结果属于已有记忆，网络搜索结果属于外部知识，都不应被重复归档。
ignored_tool_names = {
    "search_memory_tool",
    "web_search_tool",
}
TOOL_HISTORY_LABELS = {
    "search_memory_tool": ("进行了记忆检索", "记忆检索结果"),
    "web_search_tool": ("进行了网络检索", "网络检索结果"),
}

# 保留旧导入名称兼容测试及外部调用；运行时按 scene_mode 选择模板。
SYSTEM_PROMPT = PARTNER_SYSTEM_PROMPTS["realtime"]

TTS = True  # 是否进行语音合成
if TTS:
    from utils.tts import Qwen3TTSGenerator

_tts_generator = None
_tts_initialization_lock = Lock()


def get_weekday():
    weekday = datetime.datetime.now().weekday()
    # 定义星期几的列表
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    return weekdays[weekday]


def updata_num_msg_per_turn_by_accumulation(state, add_num: int):
    # 用于在每次添加messages信息时，更新updata_num_msg_per_turn内容。
    num_msg_per_turn = state["num_msg_per_turn"]
    turn_counter = state["turn_counter"]
    num_msg_per_turn[turn_counter] = num_msg_per_turn.get(
        turn_counter, 0) + add_num
    state["num_msg_per_turn"] = num_msg_per_turn

# ===========================
# 2. 状态定义 (State)
# ===========================


class AgentState(TypedDict):
    # 最多存储 MESSAGE_LEN 条消息，多余的会进行总结并存入数据库和工作记忆池
    messages: Annotated[list, add_messages]
    unsaved_messages: list  # 专门用于暂存未归档的对话历史
    is_quit: bool
    turn_counter: int
    character_setting: str
    working_memory_cache: list = []     # 工作记忆池
    working_memory_candidate: list = []  # 工作记忆候选池
    core_biography: str = ''            # 长期核心传记
    recent_memory: str = ''             # 近期记忆

    consolidation_error_count: int = 0  # 记忆整合错误报警计数
    num_msg_per_turn: Dict[int, int] = {}  # 存储每轮的消息数量 {1: 2, 2: 5, ...}
    last_activated_turn: int = 0  # 工作记忆列表 最新记忆 对应的对话轮数

    # 记忆是否正在等待或执行归档
    memory_consolidating: bool
    # 后台归档失败时保存错误信息
    memory_consolidation_error: str | None


# ===========================
# 3. 角色对话引擎
# ===========================

class CharacterChatEngine:
    """封装单个角色的模型工具和记忆资源，避免多角色之间互相覆盖。"""

    @staticmethod
    def _message_content_text(message) -> str:
        """将模型可能返回的字符串或文本块统一为可展示文本。"""
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict) and isinstance(block.get("text"), str):
                    parts.append(block["text"])
            return "\n".join(parts).strip()
        return str(content).strip() if content else ""

    @staticmethod
    def _publish_display_text(
        response_text: str,
        has_tool_calls: bool,
        config: RunnableConfig,
    ) -> None:
        """把每次模型产生的可展示文本交给当前轮次的演出队列。"""
        configurable = config.get("configurable", {})
        display_state = configurable.get("display_state")
        turn_id = configurable.get("turn_id")
        if display_state is None or not turn_id or not response_text:
            return

        source_type = (
            "reply_with_tool" if has_tool_calls else "reply_directly"
        )
        display_state.enqueue_unplanned(
            turn_id,
            source_type,
            response_text,
        )

        if not has_tool_calls:
            display_service = configurable.get("display_service")
            natural_reply = (
                display_service.parser_get_natural_text(response_text)
                if display_service is not None
                else response_text
            )
            display_state.set_final_reply(turn_id, natural_reply)

    def _publish_history_event(
        self,
        event_type: str,
        content: str,
        config: RunnableConfig | None,
        *,
        role: str = "assistant",
        speaker: str | None = None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        tool_names: list[str] | None = None,
    ) -> None:
        """持久化历史事件并加入当前页面的实时 FIFO 队列。"""
        configurable = (config or {}).get("configurable", {})
        history_store = configurable.get("history_store")
        turn_id = configurable.get("turn_id")
        if history_store is None or not turn_id or not content.strip():
            return

        if event_type == "tool_content":
            display_service = configurable.get("display_service")
            if display_service is not None:
                try:
                    content = display_service.parser_get_natural_text(content)
                except Exception:
                    pass

        try:
            history_store.append_event(
                turn_id=turn_id,
                event_type=event_type,
                role=role,
                speaker=speaker or self.true_character_name,
                content=content,
                created_at=time.time(),
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                tool_names=tool_names,
            )
        except Exception as error:
            # 历史写入失败不应中断角色回复或工具执行。
            print(f"[对话历史写入失败] {type(error).__name__}: {error}")

    def __init__(
        self,
        character_name: str,
        activity_status: CharacterActivityStatus | None = None,
        character_config: dict | None = None,
    ):
        project_root = Path(__file__).resolve().parent
        characters_dir = (project_root / "characters").resolve()
        character_dir = (characters_dir / character_name.strip()).resolve()

        if (
            not character_name.strip()
            or character_dir.parent != characters_dir
            or not character_dir.is_dir()
        ):
            raise ValueError(f"角色 '{character_name}' 不存在。")

        self.character_name = character_dir.name
        self.character_config = character_config or load_character_config(
            characters_dir,
            self.character_name,
        )
        self.true_character_name = self.character_config["character"]["true_character_name"]
        self.scene_mode = self.character_config["character"]["scene_mode"]
        self.tool_call_content_allowlist = frozenset(
            get_string_list_config(
                self.character_config,
                "display.tool_call_content_allowlist",
            )
        )
        self.base_message_turn = get_int_config(
            self.character_config, "memory.context.base_message_turn"
        )
        self.working_memory_limit = get_int_config(
            self.character_config, "memory.context.working_memory_limit"
        )
        self.biography_source_limit = get_int_config(
            self.character_config, "memory.biography.source_memory_limit"
        )
        self.short_memory_items = get_int_config(
            self.character_config, "memory.recent.short_memory_items"
        )
        self.recent_memory_items = get_int_config(
            self.character_config, "memory.recent.recent_memory_items"
        )
        self.memory_search_top_k = get_int_config(
            self.character_config, "memory.search.top_k"
        )
        self.memory_retention = {
            "low_importance_days": get_int_config(
                self.character_config,
                "memory.retention.low_importance_days",
                minimum=0,
            ),
            "medium_importance_days": get_int_config(
                self.character_config,
                "memory.retention.medium_importance_days",
                minimum=0,
            ),
            "high_importance_days": get_int_config(
                self.character_config,
                "memory.retention.high_importance_days",
                minimum=0,
            ),
            "max_capacity": get_int_config(
                self.character_config, "memory.retention.max_capacity"
            ),
            "safe_margin": get_int_config(
                self.character_config,
                "memory.retention.safe_margin",
                minimum=0,
            ),
        }
        self.activity_status = activity_status or CharacterActivityStatus()
        self.character_dir = character_dir
        self.memory_root = get_memory_root(character_dir, self.scene_mode)
        self.character_setting = read_character_setting(
            character_dir=self.character_dir,
            character_name=self.character_name
        ).strip()
        self.character_setting_summary = summary_character_setting(
            character_dir=self.character_dir,
            character_name=self.character_name,
            character_setting=self.character_setting
        )

        self.tools_by_name = {}

        embedding_fn = get_embedding_function(
            str(Path(__file__).resolve().parent / "weights" / "bge-base-zh-v1.5")
        )
        self.memory_manager = MemoryManager(
            db_path=str(self.memory_root),
            collection_name="partner_memory",
            embedding_fn=embedding_fn,
            scene_mode=self.scene_mode,
        )
        self.search_memory_tool = build_search_tool_for_character(
            self.memory_manager,
            top_k=self.memory_search_top_k,
        )
        self.recent_memory_manager = RecentMemoryManager(
            self.character_name,
            memory_root=self.memory_root,
        )
        self.tools_by_name[
            self.search_memory_tool.name
        ] = self.search_memory_tool

        self.web_search_provider = None
        self.web_search_tool = None
        if self.scene_mode == "realtime":
            success, selected_provider, message = initialize_web_search()
            if success:
                self.web_search_provider = selected_provider
                self.web_search_tool = build_web_search_tool(selected_provider)
                self.tools_by_name[self.web_search_tool.name] = self.web_search_tool
                print(f"[WebSearch] 已启用 {selected_provider}")
            else:
                print(f"[WebSearch] 网络搜索启用失败：{message}")

        self.vision_llm_with_tools = None  # 有图片时才初始化，不影响纯文本角色启动。
        self.llm_with_tools = get_llm().bind_tools(
            list(self.tools_by_name.values())
        )

    def agent_node(self, state: AgentState, config: RunnableConfig):
        """调用当前角色绑定了专属记忆工具的对话模型。"""
        num_msg_per_turn = state.get("num_msg_per_turn", {})
        first_tracked_turn = (
            min(num_msg_per_turn)
            if num_msg_per_turn
            else "暂无（首轮对话尚未完成）"
        )
        print(
            f'\n当前对话轮数 {state.get('turn_counter', 0)}\n'
            f'输入的原始对话起始轮数 {first_tracked_turn}\n'
            f'输入的近期记忆最新轮数 {state.get('last_activated_turn', 0)}\n'
        )
        prompt_values = {
            "character_setting": state["character_setting"],
            "core_biography": state["core_biography"],
            "recent_memory": state["recent_memory"],
            "working_memory": format_working_memory_for_prompt(
                state["working_memory_cache"],
                include_timestamp=self.scene_mode == "realtime",
            ),
        }
        if self.scene_mode == "realtime":
            prompt_values.update({
                "current_time": format_timestamp(time.time()),
                "weekday": get_weekday(),
            })
        elif self.scene_mode == "sandbox":
            prompt_values.update({
                "character_name": self.true_character_name,
            })
        system_prompt = PARTNER_SYSTEM_PROMPTS[self.scene_mode].format(
            **prompt_values
        )

        # 读取 display_enabled 决定是否进行演出规划
        display_enabled = config["configurable"].get("display_enabled")
        display_service = config["configurable"].get("display_service")
        need_display_prompt = display_enabled and not display_service.only_default
        print(f'need_display_prompt: {need_display_prompt}')
        if need_display_prompt:
            display_prompt = DISPLAY_PROMPT.format(
                portrait_resources=display_service.catalog.portraits_prompt,
                voice_resources=display_service.catalog.vioces_prompt
            )
            system_prompt += display_prompt

        messages_for_llm = [SystemMessage(system_prompt), *state["messages"]]
        vision_turn = config.get("configurable", {}).get("vision_turn")
        # 图片只进入本次请求副本，不写入 messages/unsaved_messages 或检查点。
        # pop 后同轮工具回环也不再发送图片；现有两次调用尝试可复用此副本。
        image_urls = vision_turn.pop("images", []) if vision_turn is not None else []
        if image_urls:
            system_prompt += VISION_PROMPT.format()
            messages_for_llm[0] = SystemMessage(system_prompt)
            human = messages_for_llm[-1]
            messages_for_llm[-1] = human.model_copy(update={"content": [
                {"type": "text", "text": human.content},
                *[{"type": "image_url", "image_url": {"url": url}} for url in image_urls],
            ]})

        print(system_prompt)

        # 因为一定会返回一条回复（即使大模型调用失败）
        # 所以再次直接将消息数量加一
        # updata_num_msg_per_turn_by_accumulation(state, 1)

        try:
            model = self.llm_with_tools
            if image_urls:
                if self.vision_llm_with_tools is None:
                    self.vision_llm_with_tools = get_vision_llm().bind_tools(list(self.tools_by_name.values()))
                model = self.vision_llm_with_tools
            # 调用一次大模型失败后，再调用一次
            try:
                response = model.invoke(messages_for_llm)
                
            except Exception as first_error:
                print(f"\n[agent_node, 大模型调用出错]: {first_error}，正在重试...")
                # 再调用一次
                response = model.invoke(messages_for_llm)

            display_name = getattr(
                self, "true_character_name", self.character_name
            )
            response_text = self._message_content_text(response)
            description, response_text = split_image_description_with_reply(response_text)
            if vision_turn is not None and description and not vision_turn["description"]:
                vision_turn["description"] = description
                self._publish_history_event(
                    "vision_description", description, config,
                )
                vision_turn["description_published"] = True
            if response_text:
                print(f"{display_name}: {response_text}")
            has_tool_calls = bool(response.tool_calls)
            if has_tool_calls:
                print(f" [{display_name} 正在调用工具]")

            tool_names = [call["name"] for call in response.tool_calls]
            if has_tool_calls:
                if response_text:
                    self._publish_history_event(
                        "tool_content",
                        response_text,
                        config,
                        tool_names=tool_names,
                    )
                else:
                    for tool_call in response.tool_calls:
                        tool_name = tool_call["name"]
                        action = TOOL_HISTORY_LABELS.get(
                            tool_name,
                            (f"调用了工具：{tool_name}", "工具结果"),
                        )[0]
                        self._publish_history_event(
                            "tool_activity",
                            f"{display_name}{action}",
                            config,
                            tool_name=tool_name,
                            tool_call_id=tool_call.get("id"),
                        )

            if (
                not has_tool_calls
                or set(tool_names).issubset(self.tool_call_content_allowlist)
            ):
                self._publish_display_text(
                    response_text,
                    has_tool_calls,
                    config,
                )

            unsaved = [*state.get("unsaved_messages", []), response]
            return {"messages": [response], "unsaved_messages": unsaved}
        except Exception as error:
            print(f"\n[agent_node, 大模型调用出错]: {error}")
            if vision_turn is not None:
                # 图片调用失败必须让前端恢复草稿，不能将道歉文本当作成功。
                raise
            # 无标记文本会由 display.py 自动使用默认演出资源。
            error_message = "抱歉，我的大脑刚刚走神了，能再说一遍吗？"
            print(f"{self.character_name}: 抱歉，我的大脑刚刚走神了，能再说一遍吗？")
            message = AIMessage(content=error_message)
            self._publish_display_text(error_message, False, config)
            unsaved = [*state.get("unsaved_messages", []), message]
            return {"messages": [message], "unsaved_messages": unsaved}
        finally:
            # 成败均释放请求副本，后续只依赖 AI 回复中的文字描述。
            image_urls.clear()
            messages_for_llm.clear()


    def retrieve_node(
        self,
        state: AgentState,
        config: RunnableConfig | None = None,
    ):
        """执行模型发起的全部已注册工具调用。"""
        results = []
        tool_request = state["messages"][-1]
        activity_status = getattr(self, "activity_status", None)

        for tool_call in tool_request.tool_calls:
            tool_name = tool_call["name"]
            tool = self.tools_by_name.get(tool_name)

            try:
                if tool is None:
                    tool_output = f"工具调用失败：未知工具 {tool_name}"
                else:
                    status_name = {
                        "search_memory_tool": "retrieving_memory",
                        "web_search_tool": "searching_web",
                    }.get(tool_name)
                    status_context = (
                        activity_status.running(status_name)
                        if status_name and activity_status is not None
                        else nullcontext()
                    )
                    with status_context:
                        tool_output = tool.invoke(tool_call["args"])
                    print(
                        f'\n[{tool_name}, {self.character_name}] 结果如下：\n{tool_output}\n')
            except Exception as error:
                tool_output = (
                    "工具调用失败："
                    f"{type(error).__name__}: {error}"
                )
            result_label = TOOL_HISTORY_LABELS.get(
                tool_name,
                ("调用了工具", "工具结果"),
            )[1]
            self._publish_history_event(
                "tool_output",
                str(tool_output),
                config,
                role="tool",
                speaker=(
                    f"{getattr(self, 'true_character_name', self.character_name)}"
                    f" · {result_label}"
                ),
                tool_name=tool_name,
                tool_call_id=tool_call.get("id"),
            )
            results.append(
                ToolMessage(
                    content=str(tool_output),
                    tool_call_id=tool_call["id"],
                    name=tool_name,
                )
            )
        unsaved = state.get("unsaved_messages", []) + results
        # updata_num_msg_per_turn_by_accumulation(state, len(results))

        return {"messages": results, "unsaved_messages": unsaved}

    def memory_consolidation_node(self, state: AgentState, config: RunnableConfig):
        """
        更新当前角色自己的记忆库和近期记忆。
        1. 进行记忆提取并入库
        2. 若提取成功：
          - 将总结的记忆放到json里，供下一次重新运行代码时生成近期记忆
          - update_working_memory_cache，更新记忆缓存
          - update_and_truncate_messages，截断messages，降低内存消耗
        3. 若提取失败：
          - 不进行以上操作
          - 等待下一次提取
        4. 按照频率清理数据库
        5. 按照频率更新用户传记
        """
        result = {}
        this_turn = state["turn_counter"]
        need_archive = (
            this_turn % NUM_CHATS_TO_SAVE == 0
            or state.get("is_quit", False)
        )
        only_exit_message = (
            state.get("is_quit", False)
            and len(state.get("unsaved_messages", [])) == 1
        )

        # 先计算并校验本轮消息数，通过节点返回值提交新状态。
        updated_num_msg_per_turn = update_num_msg_per_turn(
            state,
            this_turn,
        )
        result["num_msg_per_turn"] = updated_num_msg_per_turn

        if need_archive and not only_exit_message:

            # 获得记忆存档所需的上下文提示
            context_messages, first_unsaved_turn = get_previous_turns(
                messages=state.get("messages", []),
                unsaved_messages=state.get("unsaved_messages", []),
                num_msg_per_turn=updated_num_msg_per_turn,
                turn_counter=state.get("turn_counter", 1),
                n_turns=2
            )
            # 进行记忆提取并入库
            display_enabled = config["configurable"].get("display_enabled")
            display_service = config["configurable"].get("display_service")
            need_content_parser = display_enabled and not display_service.only_default
            new_memories, error = process_and_archive_memories(
                context_messages=context_messages,
                unsaved_messages=state.get("unsaved_messages", []),
                character_name=self.character_name,
                true_character_name=self.true_character_name,
                character_setting_summary=self.character_setting_summary,
                memory_manager=self.memory_manager,
                llm=get_llm(),
                memory_extraction_model=MemoryExtraction,
                display_service=display_service if need_content_parser else None,
                scene_mode=self.scene_mode
                # ignored_tools=ignored_tool_names,
            )

            if error is None:

                # 将总结的记忆放到json里，供下一次重新运行代码时生成近期记忆
                self.recent_memory_manager.save_new_extracted_memories(new_memories)

                # 更新工作记忆
                working_cache, working_candidate, working_memory_end_turn = (
                    update_working_memory_cache(
                        state.get("working_memory_cache", []),
                        state.get("working_memory_candidate", []),
                        new_memories,
                        turn_range=[
                            first_unsaved_turn,
                            this_turn,
                        ],
                        max_cache_size=self.working_memory_limit,
                        base_message_turn=self.base_message_turn,
                        last_activated_turn=state.get(
                            "last_activated_turn",
                            0,
                        ),
                    )
                )
                result["working_memory_cache"] = working_cache
                result["working_memory_candidate"] = working_candidate
                result["last_activated_turn"] = working_memory_end_turn

                # 只在成功后按完整轮次生成 RemoveMessage 指令。
                truncation_state = {
                    **state,
                    "num_msg_per_turn": updated_num_msg_per_turn,
                }
                result.update(
                    truncate_messages(
                        state=truncation_state,
                        turn_start=working_memory_end_turn + 1,
                    )
                )

                # 清空未保存消息，且清空失败记录
                result["unsaved_messages"] = []
                result["consolidation_error_count"] = 0

            else:
                print(f"[记忆整合出错] {error}")
                error_count = state.get("consolidation_error_count", 0) + 1
                result["consolidation_error_count"] = error_count
                print(f"\n\n[警告] 记忆提取累计失败{error_count}次！有记忆丢失风险！\n")
                new_memories = []
        

        if this_turn % NUM_CHATS_TO_CLEAN_MEMORY == 0:
            print("[记忆清理] 正在进行常规记忆清理")
            self.memory_manager.clean_memory(**self.memory_retention)

        if this_turn % NUM_CHATS_TO_UPDATE_BIO == 0:
            print("\n[用户传记] 正在更新用户传记（长期记忆）")
            # core_biography = initialize_core_biography(
            #     character_name=self.character_name,
            #     true_character_name=self.true_character_name,
            #     character_setting_summary=self.character_setting_summary,
            #     memory_manager=self.memory_manager,
            #     llm=get_llm(),
            #     long_memory_len=self.biography_source_limit,
            #     memory_root=self.memory_root,
            #     scene_mode=self.scene_mode,
            # )
            core_biography = generate_long_memory(
                memory_folder=self.memory_root,
                scene_mode=self.scene_mode,
                memory_manager=self.memory_manager,
                character_name=self.character_name,
            )
            print(f"[用户传记] 最新用户传记如下：\n{core_biography}")
            result["core_biography"] = core_biography

        result["turn_counter"] = this_turn + 1
        return result

    @staticmethod
    def route_after_agent(state: AgentState):
        last_message = state["messages"][-1]
        if getattr(last_message, "tool_calls", None):
            return "retrieve"
        return "finish"

    def build_reply_graph(self):
        workflow = StateGraph(AgentState)
        workflow.add_node("agent_node", self.agent_node)
        workflow.add_node("retrieve_node", self.retrieve_node)
        workflow.add_edge(START, "agent_node")
        workflow.add_conditional_edges(
            "agent_node",
            self.route_after_agent,
            {"retrieve": "retrieve_node", "finish": END},
        )
        workflow.add_edge("retrieve_node", "agent_node")
        return workflow.compile()

    def build_memory_graph(self):
        workflow = StateGraph(AgentState)
        workflow.add_node(
            "memory_consolidation_node",
            self.memory_consolidation_node,
        )
        workflow.add_edge(START, "memory_consolidation_node")
        workflow.add_edge("memory_consolidation_node", END)
        return workflow.compile()


# ===========================
# 4. 初始化交互与主程序
# ===========================

def get_tts_generator(character_dir: str | Path):
    """
    延迟加载并复用唯一的 Qwen3-TTS 模型实例，
    同时确保当前角色的 Voice Prompt 已初始化。
    """
    global _tts_generator

    if not TTS:
        return None

    with _tts_initialization_lock:
        try:
            project_root = Path(__file__).resolve().parent

            # 第一次调用：初始化全局唯一模型。
            if _tts_generator is None:
                print("\n[语音模型] 正在加载共享 Qwen3-TTS 模型资源，请稍候...")

                _tts_generator = Qwen3TTSGenerator(
                    model_dir=project_root / "weights" / "Qwen3-TTS-12Hz-0.6B-Base"
                )

            # 无论模型是不是刚刚初始化，
            # 都确保当前角色已经缓存 Voice Prompt。
            if not _tts_generator.init_character(character_dir):
                return None

            return _tts_generator

        except Exception as e:
            print(f"[语音模型错误] TTS 初始化失败：{e}")
            return None


def create_runtime(
    character_name: str,
    activity_status: CharacterActivityStatus | None = None,
    character_config: dict | None = None,
):
    print(f"[角色初始化] 正在加载 {character_name} ...")
    engine = CharacterChatEngine(
        character_name,
        activity_status,
        character_config,
    )

    print("\n[用户传记] 正在更新用户传记（长期记忆）")
    # core_bio = initialize_core_biography(
    #     character_name=engine.character_name,
    #     true_character_name=engine.true_character_name,
    #     character_setting_summary=engine.character_setting_summary,
    #     memory_manager=engine.memory_manager,
    #     llm=get_thinking_llm(),
    #     long_memory_len=engine.biography_source_limit,
    #     memory_root=engine.memory_root,
    #     scene_mode=engine.scene_mode,
    # )
    core_bio = generate_long_memory(
        memory_folder=engine.memory_root,
        scene_mode=engine.scene_mode,
        memory_manager=engine.memory_manager,
        character_name=engine.character_name,
    )
    print(f"[用户传记] 最新用户传记（长期记忆）如下：\n{core_bio}")

    print("\n[近期记忆] 正在加载角色的近期记忆")
    recent_memory = engine.recent_memory_manager.gen_recent_memory(
        llm=get_thinking_llm(),
        max_json_items=engine.short_memory_items,
        max_memories=engine.recent_memory_items,
        scene_mode=engine.scene_mode,
    )
    print(f"[近期记忆] 角色的近期记忆如下：\n{recent_memory}")

    reply_graph = engine.build_reply_graph()
    memory_graph = engine.build_memory_graph()

    init_state = {
        "messages": [],
        "unsaved_messages": [],
        "is_quit": False,
        "turn_counter": 1,
        "character_setting": engine.character_setting,
        "working_memory_cache": [],
        "working_memory_candidate": [],
        "core_biography": core_bio,
        "recent_memory": recent_memory,
        "consolidation_error_count": 0,
        "num_msg_per_turn": {},
        "last_activated_turn": 0,
        "memory_consolidating": False,
        "memory_consolidation_error": None,
    }

    config = {
        "recursion_limit": 1000,
        "configurable": {
            # 只有前端返回可以进行演出规划、以及display_service不为None时，才能进行演出规划
            'display_enabled': True,
            'display_service': None
        }
    }

    tts_generator = None
    try:
        tts_generator = get_tts_generator(engine.character_dir)
    except Exception as error:
        print(
            "[角色初始化警告] TTS模型初始化失败，将继续启用文本交流："
            f"{type(error).__name__}: {error}"
        )

    return (
        reply_graph,
        memory_graph,
        init_state,
        config,
        tts_generator,
        engine.character_name,
    )
