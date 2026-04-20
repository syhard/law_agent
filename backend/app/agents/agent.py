from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import os
import sys

if __package__ in (None, ""):
    backend_root = Path(__file__).resolve().parents[2]
    backend_root_str = str(backend_root)
    if backend_root_str not in sys.path:
        sys.path.insert(0, backend_root_str)

from app.agents.analyse_agent import LegalAgent as AnalyseAgent
from app.agents.decision_agent import CaseDecisionAgent
from app.agents.search_rag_agent import LegalKnowledgeBase
from app.services.legal_advisory_service import LegalAdvisoryRepository
from app.services.llm_service import get_llm
from app.agents.memory import MemoryAndContextManager  # 新增导入

DOMAIN_BOOK_KEYWORDS = {
    "contract": "合同",
    "property": "物权",
    "family": "婚姻家庭",
}

CASE_TRIGGER_KEYWORDS = [
    "合同",
    "离婚",
    "抚养",
    "继承",
    "房产",
    "借款",
    "租赁",
    "违约",
    "纠纷",
    "起诉",
    "诉讼",
    "判决",
    "赔偿",
    "法律",
    "案例",
    "案情",
]


class LegalWorkflowAgent:
    """
    总控 -> 拆解 -> 查询法规/相似案例 -> 单个判案 agent -> 回到对话
    """

    def __init__(
        self,
        llm: Optional[Any] = None,
        sqlite_path: str = "law_demo.db",
        collection_name: str = "law_demo_chunks",
        markdown_file_path: Optional[str] = None,
        user_id: str = "default_user",  # 新增：用户 ID，用于记忆隔离
    ):
        self.llm = llm or get_llm()
        self.analyse_agent = AnalyseAgent(llm=self.llm)
        self.search_agent = LegalKnowledgeBase(
            llm=self.llm,
            sqlite_path=sqlite_path,
            collection_name=collection_name,
            qdrant_url=os.getenv("QDRANT_URL"),
            qdrant_api_key=os.getenv("QDRANT_API_KEY"),
            embedding_api_key=os.getenv("EMBED_API_KEY"),
            embedding_base_url=os.getenv("EMBED_BASE_URL"),
            embedding_model="text-embedding-v3",
        )
        self.decision_agent = CaseDecisionAgent(llm=self.llm)
        self.advisory_repository = LegalAdvisoryRepository(sqlite_path=sqlite_path)
        self.markdown_file_path = markdown_file_path
        self.kb_loaded = False
        self.user_id = user_id  # 新增
        self.memory_context_manager = MemoryAndContextManager(  # 新增
            qdrant_url=os.getenv("QDRANT_URL"),
            qdrant_api_key=os.getenv("QDRANT_API_KEY"),
            collection_name='user_memory',
            embedding_api_key=os.getenv("EMBED_API_KEY"),
            embedding_base_url=os.getenv("EMBED_BASE_URL"),
        )

    def _log(self, stage: str, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[LegalWorkflowAgent][{timestamp}][{stage}] {message}")

    def init_state(self) -> Dict[str, Any]:
        return {
            "dialogue_history": [],
            "analysis_state": None,
            "workflow_mode": "chat",
            "last_completed_case": None,
        }

    def load_knowledge_base(self, markdown_file_path: Optional[str] = None) -> Dict[str, Any]:
        file_path = markdown_file_path or self.markdown_file_path
        if not file_path:
            raise ValueError("markdown_file_path is required")

        self._log("knowledge_base", f"开始加载知识库: {file_path}")
        with open(file_path, "r", encoding="utf-8") as file:
            markdown_text = file.read()

        result = self.search_agent.add_markdown_document(markdown_text)
        self.kb_loaded = True
        self.markdown_file_path = file_path
        self._log(
            "knowledge_base",
            f"知识库加载完成, article_count={result.get('article_count')}, duplicate_count={result.get('duplicate_count')}",
        )
        return result

    def run(
        self,
        user_text: str,
        state: Optional[Dict[str, Any]] = None,
        auto_load_kb: bool = False,
        markdown_file_path: Optional[str] = None,
        top_k: int = 5,
        enable_mqe: bool = True,
        mqe_count: int = 3,
        enable_hyde: bool = True,
    ) -> Dict[str, Any]:
        self._log("request", f"收到用户输入: {user_text[:80]}")

        if auto_load_kb and not self.kb_loaded:
            self.load_knowledge_base(markdown_file_path=markdown_file_path)

        state = self._normalize_state(state)
        self._append_history(state, "user", user_text)

        # 新增：存储关键信息到长期记忆
        if any(keyword in user_text for keyword in CASE_TRIGGER_KEYWORDS):
            self.memory_context_manager.store_long_term_memory(self.user_id, user_text, {"type": "case_input"})

        # 新增：1. 存储用户偏好和习惯（检测领域）
        if any(domain in user_text for domain in ["合同", "离婚", "房产", "继承"]):
            self.memory_context_manager.store_long_term_memory(
                self.user_id, 
                f"用户偏好: {user_text[:100]}", 
                {"type": "user_preference"}
            )

        # 新增：2. 存储用户对话关键片段（例如，包含情感或需求词）
        if any(keyword in user_text for keyword in ["担心", "需要", "问题", "帮助", "紧急"]):
            self.memory_context_manager.store_long_term_memory(
                self.user_id, 
                f"关键片段: {user_text[:200]}", 
                {"type": "key_fragment"}
            )

        if not self._should_start_case_workflow(user_text=user_text, state=state):
            self._log("chat", "进入普通对话流程")
            reply = self._chat_reply(user_text=user_text, state=state)
            self._append_history(state, "assistant", reply)
            return {
                "status": "chat",
                "state": state,
                "analysis_result": {
                    "status": "chat",
                    "message": reply,
                    "state": state,
                },
                "response_text": reply,
            }

        return self._run_case_workflow(
            user_text=user_text,
            state=state,
            top_k=top_k,
            enable_mqe=enable_mqe,
            mqe_count=mqe_count,
            enable_hyde=enable_hyde,
        )

    def _run_case_workflow(
        self,
        user_text: str,
        state: Dict[str, Any],
        top_k: int,
        enable_mqe: bool,
        mqe_count: int,
        enable_hyde: bool,
    ) -> Dict[str, Any]:
        state["workflow_mode"] = "case_intake"
        self._log("case", "进入案件分析流程")

        analysis_input_state = state.get("analysis_state")
        self._log("analysis", "开始案件拆解")
        analysis_result = self.analyse_agent.run(text=user_text, state=analysis_input_state)
        state["analysis_state"] = analysis_result.get("state")
        self._log(
            "analysis",
            f"案件拆解完成, status={analysis_result.get('status')}, case_domain={analysis_result.get('case_domain')}",
        )

        if analysis_result.get("status") != "ok":
            reply = self._build_followup_message(analysis_result)
            self._append_history(state, "assistant", reply)
            return {
                "status": analysis_result.get("status", "analysis_pending"),
                "state": state,
                "analysis_result": analysis_result,
                "response_text": reply,
            }

        case_domain = analysis_result.get("case_domain")
        book_keyword = DOMAIN_BOOK_KEYWORDS.get(case_domain)
        book_id = self.search_agent.get_book_id_by_title_keyword(book_keyword) if book_keyword else None

        search_query = analysis_result.get("summary") or user_text
        self._log("retrieval", f"开始法规检索, case_domain={case_domain}, book_id={book_id}")
        retrieval_results = self.search_agent.search(
            query=search_query,
            top_k=top_k,
            book_id=book_id,
            chapter_id=None,
            enable_mqe=enable_mqe,
            mqe_count=mqe_count,
            enable_hyde=enable_hyde,
        )
        self._log("retrieval", f"法规检索完成, 命中 {len(retrieval_results)} 条")

        self._log("case_search", "开始相似案例检索")
        case_results = self.advisory_repository.search_cases(
            query=search_query,
            case_domain=case_domain,
            top_k=min(top_k, 3),
        )
        self._log("case_search", f"相似案例检索完成, 命中 {len(case_results)} 条")

        self._log("decision", "开始调用单个判案 agent")
        decision_result = self.decision_agent.run(
            case_analysis=analysis_result,
            retrieval_results=retrieval_results,
            case_results=case_results,
        )
        self._log("decision", "判案结果已返回")

        # 新增：3. 存储案例判断摘要
        if decision_result.get("status") == "ok":
            summary = decision_result.get("response_text", "")[:300]  # 摘要前300字符
            if summary:
                self.memory_context_manager.store_long_term_memory(
                    self.user_id, 
                    f"案例判断摘要: {summary}", 
                    {"type": "case_summary", "case_domain": case_domain}
                )

        reply = self._build_result_reply(decision_result)
        state["workflow_mode"] = "chat_after_case"
        state["last_completed_case"] = {
            "analysis_result": analysis_result,
            "retrieval_results": retrieval_results,
            "case_results": case_results,
            "decision_result": decision_result,
            "response_text": reply,
        }
        state["analysis_state"] = None
        self._append_history(state, "assistant", reply)
        return {
            "status": "case_completed",
            "state": state,
            "analysis_result": analysis_result,
            "retrieval_results": retrieval_results,
            "case_results": case_results,
            "decision_result": decision_result,
            "response_text": reply,
        }

    def _build_result_reply(self, decision_result: Dict[str, Any]) -> str:
        conclusion = (decision_result or {}).get("conclusion")
        action_advice = (decision_result or {}).get("action_advice")

        if conclusion and action_advice:
            return f"{conclusion}\n\n下一步建议：{action_advice}"
        if conclusion:
            return conclusion
        return "判案失败，请重试。"

    def _normalize_state(self, state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if state is None:
            state = self.init_state()
        state.setdefault("dialogue_history", [])
        state.setdefault("analysis_state", None)
        state.setdefault("workflow_mode", "chat")
        state.setdefault("last_completed_case", None)
        return state

    def _append_history(self, state: Dict[str, Any], role: str, content: str) -> None:
        state["dialogue_history"].append({"role": role, "content": content})
        state["dialogue_history"] = state["dialogue_history"][-12:]
        # 新增：更新短期记忆
        self.memory_context_manager.store_short_term_memory(state, role, content)

    def _should_start_case_workflow(self, user_text: str, state: Dict[str, Any]) -> bool:
        if any(keyword in user_text for keyword in CASE_TRIGGER_KEYWORDS):
            return True
        return state.get("workflow_mode") == "case_intake"

    def _chat_reply(self, user_text: str, state: Dict[str, Any]) -> str:
        recent_case_text = self._build_recent_case_context(state.get("last_completed_case"))
        if self.llm is None:
            return self._fallback_chat_reply(recent_case_text)

        history = state.get("dialogue_history", [])[-6:]

        # 新增：获取上下文
        context = self.memory_context_manager.get_context(self.user_id, state, user_text)
        context_text = "\n".join([f"{c['source']}: {c['content']}" for c in context])

        prompt: List[Dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "你是法律咨询系统的总控对话 agent。"
                    "你先负责与用户自然对话；当用户提供案件事实时，再进入案件拆解、法规检索、相似案例检索和判案流程。"
                    "如果用户是在追问上一轮案件结果，可以继续解释，但不要凭空编造新事实。"
                    "请始终使用简体中文，回复简洁、自然、专业。"
                    f"\n相关上下文：{context_text}"  # 新增：包含上下文
                ),
            }
        ]

        if recent_case_text:
            prompt.append({"role": "system", "content": recent_case_text})

        prompt.extend(history)

        try:
            return self.llm.invoke(prompt)
        except Exception:
            return self._fallback_chat_reply(recent_case_text)

    def _fallback_chat_reply(self, recent_case_text: str = "") -> str:
        if recent_case_text:
            return "我可以继续结合刚才的案件结果为你解释，你也可以继续补充新的案情。"
        return "你好，我会先和你正常对话；当你开始提供案情时，我会自动进入案件分析与法规查询。"

    def _build_recent_case_context(self, recent_case: Optional[Dict[str, Any]]) -> str:
        if not recent_case:
            return ""
        response_text = recent_case.get("response_text", "")
        if not response_text:
            return ""
        return f"最近完成的案件结果：{response_text[:300]}"

    def _build_followup_message(self, analysis_result: Dict[str, Any]) -> str:
        status = analysis_result.get("status")

        if status == "need_clarification":
            return analysis_result.get("message", "我还不能准确判断案件类型，请再补充一些案情。")

        if status == "need_more_info":
            questions = analysis_result.get("questions") or []
            if questions:
                joined = "\n".join(f"{index + 1}. {item}" for index, item in enumerate(questions))
                return f"要继续研判这个案件，我还需要你补充这些信息：\n{joined}"
            return "要继续研判这个案件，我还需要你再补充一些关键事实。"

        return f"案件分析失败：{analysis_result.get('message', '未知错误')}"