from collections import deque
from copy import deepcopy
from pathlib import Path
from threading import Lock
from typing import Any
import json
import re


class HistoryQueueEmptyError(LookupError):
    """当前没有可领取的历史事件。"""


class HistoryQueueOrderError(RuntimeError):
    """请求的历史事件不是当前 FIFO 队首。"""


class HistoryCursorError(ValueError):
    """分页游标不属于当前历史文件。"""


class ChatHistoryStore:
    """持久化角色对话，并向当前页面按 FIFO 交付新增事件。"""

    def __init__(self, memory_root: str | Path, max_turns: int = 1000):
        if max_turns <= 0:
            raise ValueError("max_turns 必须大于 0")

        self.max_turns = max_turns
        self.directory = Path(memory_root) / "chat_history"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "history.json"
        self._lock = Lock()
        self._ready_queue = deque()

    def start_turn(
        self,
        turn_id: str,
        user_text: str,
        speaker: str,
        created_at: float,
        image_data_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        """创建新轮次并记录用户输入。"""
        event = self._new_event(
            turn_id=turn_id,
            sequence=1,
            event_type="user",
            role="user",
            speaker=speaker,
            content=user_text,
            created_at=created_at,
        )
        with self._lock:
            data = self._read_unlocked()
            if any(turn.get("turn_id") == turn_id for turn in data["turns"]):
                raise ValueError(f"历史轮次已存在：{turn_id}")

            # 附件属于用户事件，回复失败也保留；不向模型上下文添加路径。
            if image_data_urls:
                event["images"] = self._save_images(turn_id, image_data_urls)

            data["turns"].append({
                "turn_id": turn_id,
                "started_at": created_at,
                "completed_at": None,
                "status": "in_progress",
                "events": [event],
            })
            removed_turns = data["turns"][:-self.max_turns]
            data["turns"] = data["turns"][-self.max_turns:]
            try:
                self._write_unlocked(data)
            except Exception:
                self._delete_images(event.get("images", []))
                raise  # 交给原有的历史写入失败处理。
            # 先提交 JSON 再清理文件，避免写入失败时破坏旧历史。
            for turn in removed_turns:
                for old_event in turn.get("events", []):
                    self._delete_images(old_event.get("images", []))
            self._ready_queue.append(deepcopy(event))
        return event

    def image_path(self, filename: str) -> Path:
        """读取和删除共用范围检查，只允许当前记忆目录内的历史附件。"""
        if not re.fullmatch(r"image_[A-Za-z0-9_-]+_\d{2}\.jpg", filename):
            raise ValueError("无效的历史图片文件名")
        directory = (self.directory / "images").resolve()
        path = directory / filename
        if path.resolve().parent != directory:
            raise ValueError("历史图片超出附件目录")
        return path

    def _save_images(self, turn_id: str, data_urls: list[str]) -> list[str]:
        from utils.vision import history_image_bytes, MAX_CHAT_IMAGES

        filenames = []
        for index, data_url in enumerate(data_urls[:MAX_CHAT_IMAGES], 1):
            filename = f"image_{turn_id}_{index:02d}.jpg"
            try:
                path = self.image_path(filename)
                content = history_image_bytes(data_url)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                filenames.append(filename)
            except (OSError, ValueError) as error:
                print(f"[历史图片保存失败] {filename}: {error}")
                self._delete_images([filename])
        return filenames

    def _delete_images(self, filenames: list[str]) -> None:
        for filename in filenames:
            try:
                self.image_path(filename).unlink(missing_ok=True)
            except (OSError, ValueError) as error:
                print(f"[历史图片清理失败] {filename}: {error}")

    def append_event(
        self,
        turn_id: str,
        event_type: str,
        role: str,
        speaker: str,
        content: str,
        created_at: float,
        *,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        tool_names: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """将事件写入指定轮次；空内容不生成记录。"""
        content = content.strip()
        if not content:
            return None

        with self._lock:
            data = self._read_unlocked()
            turn = self._find_turn(data, turn_id)
            event = self._new_event(
                turn_id=turn_id,
                sequence=len(turn["events"]) + 1,
                event_type=event_type,
                role=role,
                speaker=speaker,
                content=content,
                created_at=created_at,
            )
            if tool_name:
                event["tool_name"] = tool_name
            if tool_call_id:
                event["tool_call_id"] = tool_call_id
            if tool_names:
                event["tool_names"] = list(tool_names)

            turn["events"].append(event)
            self._write_unlocked(data)
            self._ready_queue.append(deepcopy(event))
        return event

    def complete_turn(
        self,
        turn_id: str,
        speaker: str,
        content: str,
        completed_at: float,
    ) -> dict[str, Any]:
        """原子写入最终回复并将轮次标记为完成。"""
        with self._lock:
            data = self._read_unlocked()
            turn = self._find_turn(data, turn_id)
            event = self._new_event(
                turn_id=turn_id,
                sequence=len(turn["events"]) + 1,
                event_type="direct_reply",
                role="assistant",
                speaker=speaker,
                content=content,
                created_at=completed_at,
            )
            if content.strip():
                turn["events"].append(event)
            turn["completed_at"] = completed_at
            turn["status"] = "completed"
            self._write_unlocked(data)
            if content.strip():
                self._ready_queue.append(deepcopy(event))
        return event

    def fail_turn(self, turn_id: str, completed_at: float) -> None:
        """标记未能正常完成的轮次，不影响对话异常继续向上传递。"""
        with self._lock:
            data = self._read_unlocked()
            turn = self._find_turn(data, turn_id)
            turn["completed_at"] = completed_at
            turn["status"] = "failed"
            self._write_unlocked(data)

    def get_turns(
        self,
        limit: int = 10,
        before_turn_id: str | None = None,
    ) -> dict[str, Any]:
        """读取游标之前最近的若干完整轮次，返回顺序为旧到新。"""
        if limit <= 0:
            raise ValueError("limit 必须大于 0")

        with self._lock:
            data = self._read_unlocked()
            turns = data["turns"]
            end = len(turns)
            if before_turn_id is not None:
                for index, turn in enumerate(turns):
                    if turn.get("turn_id") == before_turn_id:
                        end = index
                        break
                else:
                    raise HistoryCursorError("历史分页游标不存在。")

            start = max(0, end - limit)
            items = deepcopy(turns[start:end])
            has_more = start > 0
            return {
                "turns": items,
                "has_more": has_more,
                "next_before_turn_id": (
                    items[0]["turn_id"] if has_more and items else None
                ),
                "total_turns": len(turns),
                "history_file_path": str(self.path.resolve()),
            }

    def snapshot(self) -> dict[str, str | None]:
        with self._lock:
            return {
                "ready_history_id": (
                    self._ready_queue[0]["event_id"]
                    if self._ready_queue
                    else None
                )
            }

    def pop_ready_event(self, event_id: str) -> dict[str, Any]:
        with self._lock:
            if not self._ready_queue:
                raise HistoryQueueEmptyError("当前没有可领取的历史事件。")
            event = self._ready_queue[0]
            if event["event_id"] != event_id:
                raise HistoryQueueOrderError(
                    "请求的历史事件不是当前待领取的队首。"
                )
            return self._ready_queue.popleft()

    @staticmethod
    def _new_event(
        *,
        turn_id: str,
        sequence: int,
        event_type: str,
        role: str,
        speaker: str,
        content: str,
        created_at: float,
    ) -> dict[str, Any]:
        return {
            "turn_id": turn_id,
            "event_id": f"{turn_id}:{sequence:04d}",
            "type": event_type,
            "role": role,
            "speaker": speaker,
            "created_at": created_at,
            "content": content.strip(),
        }

    @staticmethod
    def _find_turn(data: dict[str, Any], turn_id: str) -> dict[str, Any]:
        for turn in reversed(data["turns"]):
            if turn.get("turn_id") == turn_id:
                return turn
        raise ValueError(f"历史轮次不存在：{turn_id}")

    def _read_unlocked(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {
                "schema_version": 1,
                "max_turns": self.max_turns,
                "turns": [],
            }

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"历史文件不是有效 JSON：{self.path}") from error

        if not isinstance(data, dict) or not isinstance(data.get("turns"), list):
            raise ValueError(f"历史文件结构错误：{self.path}")
        return data

    def _write_unlocked(self, data: dict[str, Any]) -> None:
        data["schema_version"] = 1
        data["max_turns"] = self.max_turns
        content = json.dumps(data, ensure_ascii=False, indent=2)
        temporary_path = self.path.with_suffix(".json.tmp")
        temporary_path.write_text(content, encoding="utf-8")
        temporary_path.replace(self.path)
