import time
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

# 在Windows上的当前运行环境中，sentence-transformers 必须先于 Chroma
# 导入；反向顺序会让二者间接加载的 pyarrow 发生原生访问冲突。
# import sentence_transformers  # noqa: F401
import chromadb
from chromadb.utils import embedding_functions
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from .backstory_importer import (
    BACKSTORY_CATEGORY,
    BACKSTORY_IMPORTANCE,
    BACKSTORY_TIMESTAMP,
    MAX_BACKSTORY_CHARACTERS,
    backstory_metadata_from_id,
)
from .character_config import VALID_SCENE_MODES
from .relative_time import format_relative_time
from .long_memory.episode_buffer_sync import EPISODE_BUFFER_CATEGORY


_embedding_functions: dict[str, Any] = {}
_embedding_lock = Lock()


def format_timestamp(timestamp):
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


# ==========================================
# 1. 独立的 Embedding 构建函数
# ==========================================

def get_embedding_function(model_name_or_path: str):
    """
    获取进程内共享的向量化模型函数。

    不同角色通常使用同一个嵌入模型。按规范化路径缓存实例，可以避免
    每次初始化 MemoryManager 时重复加载模型，同时仍兼容不同模型路径。
    :param model_name_or_path: HuggingFace 模型名称或本地路径。
    """
    model_path = Path(model_name_or_path).expanduser()
    # 已存在的本地路径使用绝对路径作为缓存键；HuggingFace 模型名称
    # 保持原样，避免把 "organization/model" 错当成本地目录。
    model_key = (
        str(model_path.resolve())
        if model_path.exists()
        else model_name_or_path
    )

    with _embedding_lock:
        embedding_fn = _embedding_functions.get(model_key)
        if embedding_fn is None:
            print(f"[RAG] 正在加载共享 Embedding 模型: {model_key}")
            embedding_fn = (
                embedding_functions.SentenceTransformerEmbeddingFunction(
                    model_name=model_key
                )
            )
            _embedding_functions[model_key] = embedding_fn
            print(f"[RAG] 共享 Embedding 模型加载完成: {model_key}")
        return embedding_fn

# ==========================================
# 2. 核心数据库管理类
# ==========================================

class MemoryManager:
    def __init__(
        self,
        db_path: str,
        collection_name: str,
        embed_model_path: str | None = None,
        embedding_fn: Any | None = None,
        scene_mode: str = "realtime",
    ):
        """初始化持久化向量数据库"""
        if scene_mode not in VALID_SCENE_MODES:
            raise ValueError(f"非法 scene_mode：{scene_mode!r}")
        if embedding_fn is None:
            if embed_model_path is None:
                raise ValueError("embed_model_path 和 embedding_fn 至少需要提供一个。")
            embedding_fn = get_embedding_function(embed_model_path)

        self.client = chromadb.PersistentClient(path=db_path)
        self.embedding_fn = embedding_fn
        self.scene_mode = scene_mode

        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=self.embedding_fn
        )
        print(f"[RAG] 专属 ChromaDB 记忆库初始化完成，路径: {db_path}")
    
    def _remove_duplicate_if_exists(
        self, 
        memory_owner: str, 
        text: str, 
        category: str, 
        similarity_threshold: float
    ) -> int:
        """
        [内部方法] 语义查重与旧记忆清除机制。
        如果发现高度重叠的旧记忆，则将其从数据库中删除，并返回其重要度(importance)。
        如果没有重复，返回 None。
        """
        if category == BACKSTORY_CATEGORY:
            return None

        where_clause = {
            "$and": [
                {"memory_owner": memory_owner},
                {"category": category}
            ]
        }

        try:
            check_results = self.collection.query(
                query_texts=[text],
                n_results=1,
                where=where_clause
            )

            # 校验是否发现高度相似的记录
            if check_results['distances'] and len(check_results['distances'][0]) > 0:
                min_distance = check_results['distances'][0][0]
                
                if min_distance < similarity_threshold:
                    matched_id = check_results['ids'][0][0]
                    matched_doc = check_results['documents'][0][0]
                    old_importance = check_results['metadatas'][0][0].get("importance", 1)

                    print(f"\n[记忆进化] 发现语义高度重叠的旧记忆，准备进行覆盖！")
                    print(f"  -> [将被淘汰的旧表述]: '{matched_doc}'")
                    print(f"  -> [即将存入的新表述]: '{text}'")
                    print(f"  -> [相似距离]: {min_distance:.4f} (阈值: {similarity_threshold})")
                    
                    # 核心动作：直接删除旧记忆切片
                    self.collection.delete(ids=[matched_id])
                    print(f"  -> [执行动作]: 旧记忆已成功清除。")
                    
                    # 返回旧记忆的重要度，供新记忆参考
                    return old_importance

        except Exception as e:
            print(f"[记忆查重警告] 覆盖机制发生异常: {str(e)}")
            
        return None
    
    def add_memory(self, memory_owner: str, text: str, category: str, importance: int,
                   timestamp: float, chunk_size: int = 300, chunk_overlap: int = 50,
                   similarity_threshold: float = 0.15, backstory_id: str = ""):
        """
        添加记忆，通过 memory_owner 和时间戳等参数自动生成复合 doc_id，防止超出 Embedding 限制。
        :param memory_owner: 记忆的所有者（如角色名或用户名，对应规则中的 [memory_owner]）
        :param text: 记忆文本内容
        :param category: 记忆类别
        :param importance: 重要度评级
        :param timestamp: 高精度时间戳（对应规则中的 [timestamp]）
        :param chunk_size: 每个文本块的最大字符数
        :param chunk_overlap: 文本块之间的重叠字符数
        :param similarity_threshold: 距离阈值，待入库数据与库中已有数据距离小于该阈值时会被丢弃，已有数据会更新时间
        :param backstory_id: 背景故事记录的稳定标识。普通记忆保持为空字符串。
        """
        text = text.strip()
        backstory_id = backstory_id.strip()
        is_backstory = category == BACKSTORY_CATEGORY

        if not text:
            raise ValueError("记忆文本不能为空。")
        if is_backstory:
            if not backstory_id:
                raise ValueError("character_backstory 必须提供 backstory_id。")
            if importance != BACKSTORY_IMPORTANCE:
                raise ValueError(
                    f"背景故事的重要度必须为 {BACKSTORY_IMPORTANCE}。"
                )
            if float(timestamp) != BACKSTORY_TIMESTAMP:
                raise ValueError(
                    f"背景故事的时间必须为 {BACKSTORY_TIMESTAMP:g}。"
                )
            if len(text) > MAX_BACKSTORY_CHARACTERS:
                raise ValueError(
                    f"背景故事记录超过 {MAX_BACKSTORY_CHARACTERS} 个字符："
                    f"{len(text)}"
                )
            backstory_metadata = backstory_metadata_from_id(backstory_id)
        else:
            if backstory_id:
                raise ValueError(
                    "只有 character_backstory 可以提供 backstory_id。"
                )
            backstory_metadata = None

        if chunk_size <= 0:
            raise ValueError("chunk_size 必须大于 0。")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap 必须大于等于 0 且小于 chunk_size。")

        # ==========================================
        # 步骤 1：查杀旧的重复记忆
        # ==========================================
        old_importance = None
        if not is_backstory:
            old_importance = self._remove_duplicate_if_exists(
                memory_owner=memory_owner,
                text=text,
                category=category,
                similarity_threshold=similarity_threshold
            )
        
        # ==========================================
        # 步骤 2：动态调整重要度 (极其关键)
        # ==========================================
        # 融合两个记忆的权重
        if old_importance is not None:
            final_importance = int(0.5 * (old_importance + importance))
            importance = final_importance

        # ==========================================
        # 步骤 3：执行正常的分块存入逻辑
        # ==========================================
        chunks = []

        # 背景故事在导入前已经按完整记录整理好，禁止再次切块。
        if is_backstory or len(text) <= chunk_size:
            chunks.append(text)
        else:
            start = 0
            while start < len(text):
                end = min(start + chunk_size, len(text))
                chunks.append(text[start:end])
                start += (chunk_size - chunk_overlap)

        # 获取总分块数
        total_chunk_num = len(chunks)

        # 2. 准备批量插入的数据结构
        documents = []
        metadatas = []
        ids = []

        for i, chunk in enumerate(chunks):
            documents.append(chunk)

            # 3. 按照规则动态组合生成当前分块的唯一复合 ID
            # 格式："[memory_owner]_[timestamp]_[total_chunk_num]_[this_chunk_num]"
            generated_id = f"{memory_owner}_{timestamp}_{total_chunk_num}_{i+1}"
            if backstory_id:
                generated_id = f"{generated_id}_{backstory_id}"
            ids.append(generated_id)

            # 4. 组装元数据，便于未来可能需要通过 owner 或 timestamp 进行精确过滤
            metadata = {
                "category": category,
                "importance": importance,
                "timestamp": timestamp,
                "memory_owner": memory_owner,
                "backstory_id": backstory_id,
            }
            if backstory_metadata is not None:
                metadata.update(backstory_metadata)
            metadatas.append(metadata)

        # 5. 批量存入 ChromaDB
        self.collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )
        if is_backstory:
            print(
                f"[背景故事存入] {memory_owner} / {backstory_id} 已成功存入数据库。"
            )
        else:
            print(
                f"[记忆存入] 来自 {memory_owner} 的 {format_timestamp(timestamp)} 时刻的记忆，已被自动拆分为 {total_chunk_num} 块并成功存入数据库。")

    def search_memory(self, query_string: str, category: str = None,
                      min_importance: int = 1, top_k: int = 3,
                      include_backstory: bool = False,
                      display_category: bool = False) -> str:
        # 1. 将大模型传来的逗号分隔字符串拆分成列表，并限制最多5个
        queries = [q.strip() for q in query_string.split(',') if q.strip()][:5]

        if not queries:
            return "数据库中未找到相关的记忆或设定。"

        print(f" [数据库] 当前执行的多词检索列表: {queries}")

        # 2. 组装过滤条件
        conditions = []
        if category:
            conditions.append({"category": category})
        elif not include_backstory:
            conditions.append({"category": {"$ne": BACKSTORY_CATEGORY}})
        if min_importance > 1:
            conditions.append({"importance": {"$gte": min_importance}})

        where_clause = None
        if len(conditions) == 1:
            where_clause = conditions[0]
        elif len(conditions) > 1:
            where_clause = {"$and": conditions}

        # 3. 批量查询 (ChromaDB 支持同时对多个 query 进行检索)
        results = self.collection.query(
            query_texts=queries,
            n_results=top_k,
            where=where_clause
        )

        # 4. 汇总与去重
        # 由于输入了多个查询词，results 中的 documents, metadatas, ids 会变成二维列表。
        # 不同查询词可能会命中相同的文档，因此需要使用 id 进行去重。
        unique_docs = {}

        # 遍历每一个查询词对应的结果集
        for i in range(len(queries)):
            if not results['documents'][i]:
                continue

            # 提取该查询词找出的所有相关文档
            for doc_id, doc, meta in zip(results['ids'][i], results['documents'][i], results['metadatas'][i]):
                if doc_id not in unique_docs:
                    unique_docs[doc_id] = {
                        "doc": doc,
                        "meta": meta
                    }

        if not unique_docs:
            return "数据库中未找到相关的记忆或设定。"

        # 5. 格式化去重后的结果
        formatted_results = ['[查找到的信息]: ']
        for doc_info in unique_docs.values():
            doc = doc_info['doc']
            meta = doc_info['meta']
            if meta.get("category") == BACKSTORY_CATEGORY:
                tmp_result = f"- [角色背景, 重要性(1-10): {meta.get('importance')}"
                if display_category:
                    tmp_result += f", 类型: {meta.get('backstory_type')}"
                tmp_result += f"] {doc}"
                formatted_results.append(tmp_result)
            else:
                details = f"重要性(1-10): {meta.get('importance')}"
                if display_category:
                    details += f", 类别: {meta.get('category')}"
                if getattr(self, "scene_mode", "realtime") == "realtime":
                    raw_timestamp = meta.get("timestamp")
                    timestamp = datetime.fromtimestamp(raw_timestamp).strftime("%Y-%m-%d %H:%M:%S")
                    # 获得相对时间，
                    rela_time = format_relative_time(raw_timestamp)
                    if rela_time:
                        details = f"保存时间: {rela_time} ({timestamp}), {details}"
                    else:
                        details = f"保存时间: {timestamp}, {details}"
                formatted_results.append(f"- [{details}] {doc}")

        return "\n".join(formatted_results)

    def _delete_by_condition(self, rule_label: str, where_clause: dict) -> int:
        """
        [内部方法] 根据指定的 where 条件从 ChromaDB 中查询并删除数据。
        
        :param rule_label: 规则的日志标签（用于打印输出，如"低重要度"）
        :param where_clause: ChromaDB 格式的元数据过滤条件
        :return: 成功删除的记录条数
        """
        try:
            # 1. 查出所有符合过期条件的文档 IDs
            candidates = self.collection.get(
                where=where_clause,
                include=["metadatas"],
            )
            expired_records = [
                doc_id
                for doc_id, metadata in zip(
                    candidates.get("ids", []),
                    candidates.get("metadatas", []),
                )
                if metadata.get("category") not in (BACKSTORY_CATEGORY, EPISODE_BUFFER_CATEGORY)
            ]

            # 2. 如果存在过期记录，则执行批量删除
            if expired_records:
                deleted_count = len(expired_records)
                self.collection.delete(ids=expired_records)
                print(f"  -> 成功清理 {deleted_count} 条 [{rule_label}] 过期记忆。")
                return deleted_count
            
            return 0
            
        except Exception as e:
            print(f"[内存管理异常] 执行清理规则 [{rule_label}] 时出错: {str(e)}")
            return 0

    def cleanup_expired_memories(
        self,
        low_importance_days: int = 10,
        med_importance_days: int = 90,
        high_importance_days: int = None
    ) -> dict:
        """
        根据“时间 + 重要度”的分级过期机制清理记忆。
        """

        current_time = time.time()
        seconds_per_day = 86400
        stats = {"low_deleted": 0, "med_deleted": 0, "high_deleted": 0}

        print("\n[内存管理] 开始执行分级过期清理...")

        # 【规则 A】低重要度 (1 <= importance <= 4)
        if low_importance_days is not None:
            cutoff = current_time - (low_importance_days * seconds_per_day)
            where = {
                "$and": [
                    {"importance": {"$lte": 4}},
                    {"timestamp": {"$lt": cutoff}},
                    {"category": {"$ne": BACKSTORY_CATEGORY}},
                ]
            }
            stats["low_deleted"] = self._delete_by_condition("低重要度", where)

        # 【规则 B】中重要度 (5 <= importance <= 7)
        if med_importance_days is not None:
            cutoff = current_time - (med_importance_days * seconds_per_day)
            where = {
                "$and": [
                    {"importance": {"$gte": 5}},
                    {"importance": {"$lte": 7}},
                    {"timestamp": {"$lt": cutoff}},
                    {"category": {"$ne": BACKSTORY_CATEGORY}},
                ]
            }
            stats["med_deleted"] = self._delete_by_condition("中重要度", where)

        # 【规则 C】高重要度 (8 <= importance <= 10)
        if high_importance_days is not None:
            cutoff = current_time - (high_importance_days * seconds_per_day)
            where = {
                "$and": [
                    {"importance": {"$gte": 8}},
                    {"timestamp": {"$lt": cutoff}},
                    {"category": {"$ne": BACKSTORY_CATEGORY}},
                ]
            }
            stats["high_deleted"] = self._delete_by_condition("高重要度", where)

        total_deleted = sum(stats.values())
        print(f"[内存管理] 清理完成，共释放 {total_deleted} 条冗余记忆切片。\n")
        
        return stats
    
    def enforce_capacity_limit(self, max_capacity: int = 5000, safe_margin: int = 500) -> int:
        """
        极端情况兜底：当数据库容量超出最大限制时，强制触发 LRU 淘汰机制。
        建议在调用 cleanup_expired_memories 之后调用此方法。

        :param max_capacity: 数据库允许的最大条目数（触发红线）。应为safe_margin的两倍及其以上。
        :param safe_margin: 缓冲带。触发清理后，额外多删一部分，避免每次写入都频繁触发清理。
        :return: 实际强制删除的条目数。
        """
        if max_capacity < 2*safe_margin:
            print('[参数不合规] max_capacity必须是safe_margin的2倍以上! 本次不进行删除操作!')
            return 0
        try:
            # 1. 提取全量数据的 id 和 metadata (因为 ChromaDB 不支持数据库层面的高级排序)
            # 注意：仅提取 metadatas，不提取 documents(文本本身)，极大节省内存开销
            all_data = self.collection.get(include=["metadatas"])
            all_ids = all_data.get("ids", [])
            all_metadatas = all_data.get("metadatas", [])
            records = [
                (doc_id, metadata)
                for doc_id, metadata in zip(all_ids, all_metadatas)
                if metadata.get("category") not in (BACKSTORY_CATEGORY, EPISODE_BUFFER_CATEGORY)
            ]
            # 背景故事和事件缓存由源文件管理，不参与自动淘汰。
            protected_count = len(all_ids) - len(records)
            current_count = len(records)

            if current_count <= max_capacity:
                return 0

            # 只按普通记忆容量计算超出部分，受保护类别不占份额。
            delete_count = min(
                (current_count - max_capacity) + safe_margin,
                current_count,
            )

            print(
                f"\n[容量警报] 当前普通记忆容量 ({current_count}) 已超载！"
                f"最大限制: {max_capacity}；另有 {protected_count} 条背景故事／事件缓存不计入容量。"
            )
            print(f"[内存管理] 触发智能 LRU 强制淘汰，计划清理 {delete_count} 条边缘记忆...")

            # 3. 核心排序逻辑：优先按 importance 升序，如果 importance 相同，再按 timestamp 升序
            # 结果就是：最前面的一定是 [重要度最低] 且 [最古老] 的记忆。
            records.sort(
                key=lambda x: (x[1].get("importance", 1), x[1].get("timestamp", 0))
            )

            # 4. 截取需要被淘汰的牺牲品 IDs
            ids_to_delete = [record[0] for record in records[:delete_count]]

            # 5. 执行批量删除
            if ids_to_delete:
                self.collection.delete(ids=ids_to_delete)
                print(f"[内存管理] 强制清理完成，成功释放 {len(ids_to_delete)} 条记忆片段。\n")
                return len(ids_to_delete)
                
        except Exception as e:
            print(f"[内存管理异常] 执行 LRU 兜底机制时出错: {str(e)}")
            
        return 0

    def clean_memory(
        self,
        low_importance_days: int = 20,
        medium_importance_days: int = 600,
        high_importance_days: int = 0,
        max_capacity: int = 5000,
        safe_margin: int = 500,
    ):
        """
        全自动记忆维护管家。
        先执行温柔的“过期清理”，如果清理完还是超载，再执行暴力的“LRU 兜底”。
        """
        print("\n=== 开始执行常规记忆库维护 ===")
        
        # 1. 先进行基于时间和重要度的常规清理
        self.cleanup_expired_memories(
            low_importance_days=low_importance_days,
            med_importance_days=medium_importance_days,
            # TOML 没有 null，配置中的 0 表示永久保留。
            high_importance_days=(high_importance_days or None),
        )
        
        # 2. 检查是否需要兜底（假设你的机器配置最多承载 5000 条切片）
        # safe_margin 设为 500，意味着一旦超过 5000，会直接删到剩下 4500，留出喘息空间
        self.enforce_capacity_limit(
            max_capacity=max_capacity,
            safe_margin=safe_margin,
        )
        
        print("=== 记忆库维护完成 ===\n")

    def get_top_memories(self, limit: int = 30, min_importance: int = 5,
                         include_backstory: bool = False) -> list[dict]:
        """
        获取系统中最重要的记忆。
        
        获取策略：
        1. 数据库层面预过滤：只查询重要度 >= min_importance 的数据。
        2. 极简网络IO：第一阶段仅拉取 ids 和 metadatas，不拉取体积最大的 documents。
        3. 内存排序：在内存中按 (importance DESC, timestamp DESC) 对轻量级数据进行排序。
        4. 精确回表：仅根据排好序的 Top-K ID，二次请求数据库获取完整的文档内容。
        
        :param limit: 返回的最大记忆数量
        :param min_importance: 记忆重要度的最低门槛（超参数，默认为 5）
        :return: 排序后的重要记忆列表 [{"text": "...", "importance": 9, "timestamp": 1700000}, ...]
        """
        # ==========================================
        # 阶段一：轻量级条件查询 (仅获取元数据和ID)
        # ==========================================
        try:
            conditions = [{"importance": {"$gte": min_importance}}]
            if not include_backstory:
                conditions.append(
                    {"category": {"$ne": BACKSTORY_CATEGORY}}
                )
            where_clause = (
                conditions[0]
                if len(conditions) == 1
                else {"$and": conditions}
            )
            # 使用 where 条件过滤，并通过 include 限制仅返回 metadatas（ids 默认总是返回）
            metadata_results = self.collection.get(
                where=where_clause,
                include=['metadatas'] 
            )
        except Exception as e:
            print(f"[RAG] 提取记忆元数据时发生错误: {e}")
            return []

        fetched_ids = metadata_results.get('ids', [])
        fetched_metas = metadata_results.get('metadatas', [])

        if not fetched_ids or not fetched_metas:
            return []

        # ==========================================
        # 阶段二：提取排序键并在内存中进行多级排序
        # ==========================================
        # 组装成轻量级的元组列表: (id, importance, timestamp)
        sortable_items = []
        for doc_id, meta in zip(fetched_ids, fetched_metas):
            importance = meta.get('importance', 0)
            timestamp = meta.get('timestamp', 0.0)
            sortable_items.append((doc_id, importance, timestamp))

        # 执行双重降序排序
        sorted_items = sorted(
            sortable_items, 
            key=lambda x: (x[1], x[2]), 
            reverse=True
        )

        # 截取 Top-K 的数据，并提取出对应的 IDs
        top_k_items = sorted_items[:limit]
        top_k_ids = [item[0] for item in top_k_items]

        if not top_k_ids:
            return []

        # ==========================================
        # 阶段三：精确回表 (仅拉取 Top-K 的完整文档)
        # ==========================================
        try:
            # 利用 ids 参数精准拉取，此时需要完整的 documents 和 metadatas
            final_results = self.collection.get(
                ids=top_k_ids,
                include=['documents', 'metadatas']
            )
        except Exception as e:
            print(f"[RAG] 回表获取完整记忆时发生错误: {e}")
            return []

        # 注意：ChromaDB get(ids=...) 返回的顺序不一定与传入的 ids 顺序严格一致。
        # 因此，需要构建一个哈希映射表（字典），以 O(1) 的复杂度重新恢复之前排好的严格顺序。
        doc_lookup = {}
        for doc_id, doc, meta in zip(final_results['ids'], final_results['documents'], final_results['metadatas']):
            doc_lookup[doc_id] = {
                "text": doc,
                "importance": meta.get('importance', 0),
                "timestamp": meta.get('timestamp', 0.0)
            }

        # ==========================================
        # 阶段四：按照 Top-K ID 的顺序组装最终结果
        # ==========================================
        final_memories = []
        for doc_id in top_k_ids:
            if doc_id in doc_lookup:
                final_memories.append(doc_lookup[doc_id])

        return final_memories

    def count_memories_by_importance(self, min_importance: int = 1,
                                     max_importance: int = 10,
                                     include_backstory: bool = False) -> int:
        """
        统计指定重要度区间内的记忆数量。
        
        :param min_importance: 最小重要度 (包含)
        :param max_importance: 最大重要度 (包含)
        :return: 满足条件的记忆总数量
        """
        # 1. 参数校验：防止输入反向区间
        if min_importance > max_importance:
            print(f"[RAG] 警告：最小重要度 ({min_importance}) 大于最大重要度 ({max_importance})，已自动互换。")
            min_importance, max_importance = max_importance, min_importance

        # 2. 组装 ChromaDB 的复合条件查询
        conditions = [
            {"importance": {"$gte": min_importance}},
            {"importance": {"$lte": max_importance}},
        ]
        if not include_backstory:
            conditions.append({"category": {"$ne": BACKSTORY_CATEGORY}})
        where_clause = {"$and": conditions}

        # 3. 极速查询逻辑
        try:
            # 仅仅利用 where 条件在底层进行筛选，最后只返回匹配的 ids 即可
            results = self.collection.get(
                where=where_clause,
                include=[] 
            )
            
            # 返回的 ids 列表的长度，就是该区间的记忆总数
            memory_count = len(results.get('ids', []))
            return memory_count
            
        except Exception as e:
            print(f"[RAG] 统计区间 {min_importance}-{max_importance} 记忆数量时发生错误: {e}")
            return 0

    @staticmethod
    def _time_range_conditions(
        start_time: str | float,
        end_time: str | float,
        include_backstory: bool = False,
    ) -> list[dict]:
        """解析本地时间；纯日期结束值包含全天，精确时间结束值包含该时刻。"""
        from datetime import timedelta
        import math

        def parse_time(value):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                timestamp = float(value)
                if not math.isfinite(timestamp):
                    raise ValueError("时间戳必须是有限数值。")
                return timestamp, None
            if isinstance(value, str):
                value = value.strip()
                try:
                    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").timestamp(), None
                except ValueError:
                    try:
                        day = datetime.strptime(value, "%Y-%m-%d")
                    except ValueError:
                        raise ValueError(
                            f"无法识别的时间格式: {value}。请使用 "
                            "'YYYY-MM-DD' 或 'YYYY-MM-DD HH:MM:SS'"
                        ) from None
                    return day.timestamp(), day
            raise TypeError("时间参数必须是字符串、整数或浮点数。")

        start = parse_time(start_time)
        end = parse_time(end_time)
        if start[0] > end[0]:
            print("[RAG] 警告：开始时间晚于结束时间，已自动互换。")
            start, end = end, start

        # 先互换原始边界，再展开结束日期，避免反向日期范围少算一天。
        end_operator = "$lte"
        end_ts = end[0]
        if end[1] is not None:
            end_ts = (end[1] + timedelta(days=1)).timestamp()
            end_operator = "$lt"

        conditions = [
            {"timestamp": {"$gte": start[0]}},
            {"timestamp": {end_operator: end_ts}},
        ]
        if not include_backstory:
            conditions.append({"category": {"$ne": BACKSTORY_CATEGORY}})
        return conditions

    def get_memories_by_time_range(
        self,
        start_time: str | float,
        end_time: str | float,
        *,
        sample_threshold: int = 100,
        category: str | None = None,
        memory_owner: str | None = None,
        min_importance: int = 1,
        include_backstory: bool = False,
    ) -> dict:
        """
        按日期范围检索数据库记录，以 (timestamp, id) 升序返回。

        支持 YYYY-MM-DD、YYYY-MM-DD HH:MM:SS 和 Unix 时间戳。
        纯日期结束值包含当天，精确时间结束值包含该时刻；反向范围自动互换。
        记录数超过 sample_threshold 时，按排序后的位置均匀采样该数量，
        并保留首尾记录。阈值必须为至少 2 的整数。计数及采样单位为数据库切片。
        时间依据元数据 timestamp，而非正文中的事件发生时间。
        """
        if type(sample_threshold) is not int or sample_threshold < 2:
            raise ValueError("sample_threshold 必须是大于等于 2 的整数。")

        conditions = self._time_range_conditions(
            start_time, end_time, include_backstory or bool(category)
        )
        if category:
            conditions.append({"category": category})
        if memory_owner:
            conditions.append({"memory_owner": memory_owner})
        if min_importance > 1:
            conditions.append({"importance": {"$gte": min_importance}})

        metadata_results = self.collection.get(
            where={"$and": conditions}, include=["metadatas"]
        )
        items = sorted(
            zip(metadata_results["ids"], metadata_results["metadatas"]),
            key=lambda item: (item[1]["timestamp"], item[0]),
        )
        total_count = len(items)
        sampled = total_count > sample_threshold
        if sampled:
            items = [
                items[i * (total_count - 1) // (sample_threshold - 1)]
                for i in range(sample_threshold)
            ]

        selected_ids = [doc_id for doc_id, _ in items]
        memories = []
        if selected_ids:
            results = self.collection.get(
                ids=selected_ids, include=["documents", "metadatas"]
            )
            lookup = {
                doc_id: {
                    "id": doc_id,
                    "text": doc,
                    "timestamp": meta["timestamp"],
                    "category": meta.get("category"),
                    "importance": meta.get("importance", 0),
                    "memory_owner": meta.get("memory_owner"),
                }
                for doc_id, doc, meta in zip(
                    results["ids"], results["documents"], results["metadatas"]
                )
            }
            memories = [lookup[doc_id] for doc_id in selected_ids if doc_id in lookup]

        return {
            "total_count": total_count,
            "returned_count": len(memories),
            "sampled": sampled,
            "memories": memories,
        }

    def count_memories_by_time_range(self, start_time: str | float,
                                     end_time: str | float,
                                     include_backstory: bool = False) -> int:
        """
        按照时间范围统计数据库中的记忆数量。

        支持 YYYY-MM-DD、YYYY-MM-DD HH:MM:SS 和 Unix 时间戳。
        纯日期结束值使用次日零点作为排他上界，包含结束日期全天；
        精确时间结束值使用包含边界。反向范围自动互换。
        """
        try:
            conditions = self._time_range_conditions(
                start_time, end_time, include_backstory
            )
        except Exception as e:
            print(f"[RAG] 时间解析错误: {e}")
            return 0

        try:
            results = self.collection.get(
                where={"$and": conditions},
                include=[],
            )
            return len(results.get("ids", []))
        except Exception as e:
            print(f"[RAG] 统计时间范围记忆数量时发生错误: {e}")
            return 0


# ==========================================
# 3. 动态工具工厂
# ==========================================

def build_search_tool_for_character(
    memory_manager: MemoryManager,
    top_k: int = 3,
):
    """
    闭包工厂：为特定角色生成专属的记忆检索工具。
    """
    class SearchMemoryInput(BaseModel):
        # 修改 description，引导大模型输出多个以逗号分隔的检索词
        query: str = Field(..., description="检索的关键词或核心短语。为了提高检索全面性，可以根据用户问题提取出多个相关的不同检索词（至少2个，最多5个），并严格使用英文逗号 ',' 分隔。例如：'喜欢的食物,水果,旅行经历'")
        category: str = Field(
            None, description="【可选】记忆类别过滤。可选值：'user_fact', 'character_setting', 'event', 'character_backstory', 'episode_buffer'（经过一定整理的重要共同经历），默认检索全部类别的记忆。")
        min_importance: int = Field(1, description="【可选】最低重要度过滤 (1-10)。默认 1。")
        include_backstory: bool = Field(
            True,
            description="【可选】未指定类别category时，是否把角色背景故事包含在检索范围内。默认包含背景故事。",
        )

    @tool("search_memory_tool", args_schema=SearchMemoryInput)
    def search_memory_tool(query: str, category: str = None,
                           min_importance: int = 1,
                           include_backstory: bool = False) -> str:
        """
        当你遇到以下情况且无法从对话历史获得足够信息时，必须调用此工具，依靠输出的记忆信息进行回复：
        1. 用户问你“还记得XXX吗？”或提及过去的事件。
        2. 你需要了解用户的个人喜好或基本信息以便给出更好的回答。
        3. 你需要查阅或核实你自己的详细角色设定。
        4. 你需要回忆过去的重要经历、人物关系或对事物的认知。
        """
        return memory_manager.search_memory(
            query,
            category,
            min_importance,
            top_k=top_k,
            include_backstory=include_backstory,
        )

    return search_memory_tool
