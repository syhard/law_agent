import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"(\{.*\})", text, re.S)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except Exception:
            return None


class CaseDecisionAgent:
    """
    单个判案 agent：
    根据案件拆解结果、法条检索结果、相似案例结果，输出中文结论与行动建议。
    """

    def __init__(self, llm: Any):
        self.llm = llm

    def _log(self, stage: str, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[CaseDecisionAgent][{timestamp}][{stage}] {message}")

    def _ensure_chinese_text(self, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        if re.search(r"[\u4e00-\u9fff]", value):
            return value
        if self.llm is None:
            return value

        prompt = [
            {
                "role": "system",
                "content": "请将以下内容准确翻译并整理为自然、专业的简体中文，只返回中文结果。",
            },
            {"role": "user", "content": value},
        ]
        try:
            translated = self.llm.invoke(prompt)
            return translated or value
        except Exception:
            return value

    def _ensure_chinese_result(self, payload: Any) -> Any:
        if isinstance(payload, dict):
            return {key: self._ensure_chinese_result(value) for key, value in payload.items()}
        if isinstance(payload, list):
            return [self._ensure_chinese_result(item) for item in payload]
        return self._ensure_chinese_text(payload)

    def run(
        self,
        case_analysis: Dict[str, Any],
        retrieval_results: List[Dict[str, Any]],
        case_results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if self.llm is None:
            raise ValueError("LLM is required for case decision.")
        if not case_analysis:
            raise ValueError("case_analysis cannot be empty.")
        if not retrieval_results:
            raise ValueError("retrieval_results cannot be empty.")

        self._log("decision", "开始生成单个判案 agent 结论")
        prompt = self._build_prompt(case_analysis, retrieval_results, case_results)
        response = self.llm.invoke(prompt)
        parsed = _extract_json(response)
        if not parsed:
            raise ValueError("CaseDecisionAgent did not return valid JSON.")

        parsed = self._ensure_chinese_result(parsed)
        self._log("decision", "判案结果生成完成")
        return parsed

    def _build_prompt(
        self,
        case_analysis: Dict[str, Any],
        retrieval_results: List[Dict[str, Any]],
        case_results: List[Dict[str, Any]],
    ) -> List[Dict[str, str]]:
        trimmed_laws = [
            {
                "article_no": item.get("article_no"),
                "article_num": item.get("article_num"),
                "full_path": item.get("full_path"),
                "content": item.get("content"),
                "score": item.get("score"),
            }
            for item in retrieval_results[:8]
        ]
        trimmed_cases = [
            {
                "title": item.get("title"),
                "case_domain": item.get("case_domain"),
                "summary": item.get("summary"),
                "judgment_points": item.get("judgment_points"),
                "court": item.get("court"),
                "score": item.get("score"),
            }
            for item in case_results[:5]
        ]

        schema = {
            "case_type": "案件类型，必须使用中文",
            "conclusion": "一段中文结论，必须明确写出依据哪些法条得出判断",
            "action_advice": "一段中文行动建议，说明用户下一步该怎么做",
            "legal_basis": [
                {
                    "article_no": "法条条号",
                    "full_path": "法条路径",
                    "reason": "该法条为什么适用于本案",
                }
            ],
            "recommended_laws": [
                {
                    "article_no": "建议展示给用户的法条条号",
                    "full_path": "法条路径",
                    "content": "法条内容",
                    "reason": "推荐原因",
                }
            ],
            "recommended_cases": [
                {
                    "title": "建议展示给用户的相关案例标题",
                    "court": "法院",
                    "summary": "案例摘要",
                    "reason": "推荐原因",
                }
            ],
            "risk_warning": ["风险提示1", "风险提示2"],
            "needed_evidence": ["建议补充的证据1", "建议补充的证据2"],
        }

        return [
            {
                "role": "system",
                "content": (
                    "你是一个法律判案 agent。"
                    "你的任务是根据案件拆解结果、法条检索结果和相似案例结果，给出谨慎、客观、可执行的中文研判。"
                    "必须使用简体中文。"
                    "不要编造事实，不要引用未提供的法条。"
                    "如果某些法条和案例与你的结论高度相关，请放入 recommended_laws 和 recommended_cases 返回给用户。"
                    "只返回 JSON。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"案件分析结果：\n{json.dumps(case_analysis, ensure_ascii=False, indent=2)}\n\n"
                    f"检索到的法条：\n{json.dumps(trimmed_laws, ensure_ascii=False, indent=2)}\n\n"
                    f"相似案例：\n{json.dumps(trimmed_cases, ensure_ascii=False, indent=2)}\n\n"
                    "要求：\n"
                    "1. conclusion 必须写成一段中文，并明确写出依据哪些法条得出结论。\n"
                    "2. action_advice 必须写成一段中文，说明用户下一步该怎么做。\n"
                    "3. 如果某些法条和案例特别相关，就返回给用户。\n\n"
                    f"请按以下 JSON 结构返回：\n{json.dumps(schema, ensure_ascii=False, indent=2)}"
                ),
            },
        ]
