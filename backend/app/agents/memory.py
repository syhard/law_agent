import os
import uuid
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import math
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, Filter, FieldCondition, MatchValue
from openai import OpenAI

class MemoryAndContextManager:
    """
    记忆管理与上下文管理类：
    - 短期记忆：存储在内存中的对话历史。
    - 长期记忆：使用 Qdrant 存储关键信息，一个 collection 通过 user_id 字段筛选。
    - 上下文管理：从短期和长期记忆中通过向量相似度筛选关键上下文。
    """
    def __init__(self, qdrant_url: str, qdrant_api_key: str, collection_name: str = "user_memories", embedding_api_key: str = "", embedding_base_url: str = "", embedding_model: str = "text-embedding-v3"):
        self.qdrant_client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
        self.collection_name = collection_name
        self.embedding_api_key = embedding_api_key
        self.embedding_base_url = embedding_base_url
        self.embedding_model = embedding_model
        
        # 初始化 OpenAI 客户端用于嵌入
        self.embedding_client = OpenAI(
            api_key=self.embedding_api_key,
            base_url=self.embedding_base_url
        )
        
        # 确保 collection 存在
        if not self.qdrant_client.collection_exists(self.collection_name):
            self.qdrant_client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=1024, distance=Distance.COSINE)
            )
        self._ensure_payload_indexes()

    def _ensure_payload_indexes(self):
        for field_name, field_schema in (
            ("user_id", "keyword"),
            ("type", "keyword"),
            ("timestamp", "datetime"),
        ):
            try:
                self.qdrant_client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field_name,
                    field_schema=field_schema,
                )
            except Exception:
                pass

    def _get_embedding(self, text: str) -> List[float]:
        """使用 OpenAI 嵌入 API 获取文本嵌入"""
        try:
            resp = self.embedding_client.embeddings.create(
                model=self.embedding_model,
                input=text
            )
            return resp.data[0].embedding
        except Exception as e:
            print(f"嵌入 API 调用失败: {e}")
            # 返回空嵌入作为备选
            return [0.0] * 1536

    def _generate_point_id(self) -> str:
        """生成有效的点 ID（使用 UUID）"""
        return str(uuid.uuid4())

    def _qdrant_search(
        self,
        query_vector: List[float],
        top_k: int,
        q_filter: Optional[Filter] = None,
    ):
        """
        Compatible with both old and new qdrant-client APIs.
        """
        if hasattr(self.qdrant_client, "search"):
            return self.qdrant_client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                query_filter=q_filter,
                limit=top_k,
                with_payload=True,
                with_vectors=False,
            )

        if hasattr(self.qdrant_client, "query_points"):
            response = self.qdrant_client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                query_filter=q_filter,
                limit=top_k,
                with_payload=True,
                with_vectors=False,
            )

            if hasattr(response, "points"):
                return response.points
            if isinstance(response, tuple) and response:
                return response[0]
            return response

        raise AttributeError(
            "Current qdrant-client does not provide 'search' or 'query_points'."
        )

    def store_long_term_memory(self, user_id: str, key_info: str, metadata: Optional[Dict[str, Any]] = None):
        """存储长期记忆到 Qdrant，一个 collection 通过 user_id 筛选"""
        embedding = self._get_embedding(key_info)
        timestamp = datetime.now().isoformat()  # 添加时间戳
        point_id = self._generate_point_id()  # 使用 UUID 作为点 ID
        payload = {"text": key_info, "user_id": user_id, "timestamp": timestamp, **(metadata or {})}
        self.qdrant_client.upsert(
            collection_name=self.collection_name,
            points=[{
                "id": point_id,  # UUID 字符串
                "vector": embedding,
                "payload": payload
            }]
        )

    def retrieve_long_term_memory(self, user_id: str, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """从长期记忆检索相似信息，通过 user_id 筛选，混合向量相似度和时间近因性"""
        embedding = self._get_embedding(query)
        filter_condition = Filter(
            must=[
                FieldCondition(
                    key="user_id",
                    match=MatchValue(value=user_id)
                )
            ]
        )
        results = self._qdrant_search(  # 使用兼容方法
            query_vector=embedding,
            top_k=top_k * 2,  # 获取更多以便排序
            q_filter=filter_condition,
        )
        
        now = datetime.now()
        tau = timedelta(hours=24)  # 半衰期 24 小时
        mixed_results = []
        for hit in results:
            similarity_score = hit.score
            timestamp_str = hit.payload.get("timestamp")
            if timestamp_str:
                timestamp = datetime.fromisoformat(timestamp_str)
                delta_t = now - timestamp
                # 指数衰减：24 小时内高分，之后衰减
                time_decay = math.exp(-delta_t.total_seconds() / tau.total_seconds()) if delta_t > timedelta(hours=24) else 1.0
                mixed_score = similarity_score * time_decay  # 混合权重：相似度 * 时间衰减
            else:
                mixed_score = similarity_score  # 无时间戳时使用相似度
            mixed_results.append({
                "text": hit.payload["text"],
                "score": mixed_score,
                "original_score": similarity_score,
                "timestamp": timestamp_str
            })
        
        # 按混合分数排序并返回 top_k
        mixed_results.sort(key=lambda x: x["score"], reverse=True)
        return mixed_results[:top_k]

    def store_short_term_memory(self, state: Dict[str, Any], role: str, content: str):
        """短期记忆：更新 state 中的对话历史"""
        state.setdefault("dialogue_history", [])
        state["dialogue_history"].append({"role": role, "content": content})
        state["dialogue_history"] = state["dialogue_history"][-10:]

    def get_context(self, user_id: str, state: Dict[str, Any], current_query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """获取上下文：结合短期记忆和长期记忆，通过相似度筛选"""
        short_term = state.get("dialogue_history", [])[-5:]
        long_term = self.retrieve_long_term_memory(user_id, current_query, top_k=top_k)
        
        context = []
        for item in short_term:
            context.append({"source": "short_term", "content": item["content"], "score": 1.0})
        for item in long_term:
            context.append({"source": "long_term", "content": item["text"], "score": item["score"]})
        
        context.sort(key=lambda x: x["score"], reverse=True)
        return context[:top_k]
