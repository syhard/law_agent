import json
import re
from typing import Any, Dict, List, Optional


CASE_SCHEMAS: Dict[str, Dict[str, Dict[str, str]]] = {
    "contract": {
        "required": {
            "core_facts": "案件核心事实",
            "user_goal": "用户目标",
            "contract_type": "合同类型",
            "contract_counterparty": "合同相对方",
            "breach_fact": "违约事实",
        },
        "optional": {
            "amount_involved": "涉及金额",
            "evidence": "现有证据",
        },
    },
    "property": {
        "required": {
            "core_facts": "案件核心事实",
            "user_goal": "用户目标",
            "property_object": "争议财产",
            "ownership_status": "权属情况",
            "dispute_behavior": "争议行为",
        },
        "optional": {
            "evidence": "现有证据",
        },
    },
    "family": {
        "required": {
            "core_facts": "案件核心事实",
            "user_goal": "用户目标",
            "relationship_type": "关系类型",
            "current_status": "当前关系状态",
            "core_dispute": "核心争议",
        },
        "optional": {
            "children_info": "子女情况",
            "property_info": "财产情况",
        },
    },
}


FIELD_QUESTIONS: Dict[str, str] = {
    "core_facts": "请简单描述一下事情经过。",
    "user_goal": "你希望我帮你达到什么目标？",
    "contract_type": "这是什么类型的合同，比如借款、买卖、租赁？",
    "contract_counterparty": "合同相对方是谁？",
    "breach_fact": "对方具体存在哪些违约行为？",
    "amount_involved": "这次纠纷大概涉及多少金额？",
    "evidence": "你手里目前有哪些证据，比如合同、聊天记录、转账记录？",
    "property_object": "争议的财产具体是什么？",
    "ownership_status": "目前谁主张对该财产享有权利？",
    "dispute_behavior": "对方实施了什么争议行为？",
    "relationship_type": "你和对方是什么关系？",
    "current_status": "你们目前的关系状态是怎样的？",
    "core_dispute": "目前最主要的争议点是什么？",
    "children_info": "如果涉及子女，请补充一下子女情况。",
    "property_info": "如果涉及夫妻或家庭财产，请补充财产情况。",
}


FIELD_KEYWORDS: Dict[str, List[str]] = {
    "contract_type": ["合同", "借款", "买卖", "租赁", "加盟", "服务", "劳动", "协议"],
    "contract_counterparty": ["对方", "公司", "乙方", "甲方", "房东", "租客", "卖家", "买家"],
    "breach_fact": ["违约", "不履行", "逾期", "拖欠", "拒不", "没交付", "没付款", "没退款"],
    "amount_involved": ["元", "万", "金额", "价款", "赔偿", "转账"],
    "evidence": ["录音", "聊天", "微信", "转账", "发票", "收据", "截图", "证据", "证明"],
    "property_object": ["房", "车", "存款", "股权", "财产", "遗产", "房产"],
    "ownership_status": ["登记", "产权", "名字", "共有", "所有权", "权属"],
    "dispute_behavior": ["占有", "转移", "处分", "侵占", "拒绝返还", "擅自出售"],
    "relationship_type": ["夫妻", "离婚", "同居", "父母", "子女", "抚养", "继承"],
    "current_status": ["分居", "离婚", "已婚", "未离婚", "同住", "冷静期"],
    "core_dispute": ["抚养权", "抚养费", "探视", "财产分割", "继承份额"],
    "children_info": ["孩子", "子女", "抚养", "上学"],
    "property_info": ["房产", "车", "存款", "彩礼", "共同财产"],
}


DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "contract": ["合同", "协议", "借款", "欠款", "租赁", "租房", "房东", "押金", "买卖", "违约", "退款", "货款", "加盟"],
    "property": ["房产", "房屋", "车辆", "车位", "财产", "产权", "继承", "遗产", "返还", "过户"],
    "family": ["离婚", "婚姻", "夫妻", "子女", "抚养", "探视", "彩礼", "同居"],
}


def parse_json(text: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
    if not text:
        return fallback
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"(\{.*\})", text, re.S)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                return fallback
    return fallback


def merge(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(old)
    for key, value in new.items():
        if value not in (None, "", [], {}):
            result[key] = value
    return result


def find_missing(info: Dict[str, Any], schema: Dict[str, Dict[str, str]]) -> List[str]:
    return [field for field in schema["required"] if not info.get(field)]


def build_questions(fields: List[str]) -> List[str]:
    return [FIELD_QUESTIONS.get(field, f"请补充 {field}。") for field in fields[:3]]


def summarize_text(text: str, limit: int = 120) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit].rstrip()}..."


def first_sentence_with_keyword(text: str, keywords: List[str]) -> Optional[str]:
    sentences = [part.strip("，。；; ") for part in re.split(r"[。；;\n]", text) if part.strip()]
    for sentence in sentences:
        if any(keyword in sentence for keyword in keywords):
            return sentence
    return None


class CaseClassifier:
    def __init__(self, llm: Optional[Any] = None):
        self.llm = llm

    def classify(self, text: str) -> str:
        if self.llm:
            print('a')
            prompt = (
                "请将下面的法律咨询文本分类为 property、contract、family 或 unclear。"
                "只返回 JSON，例如 {\"case_domain\": \"contract\"}。\n\n"
                f"用户输入：{text}"
            )
            try:
                resp = self.llm.invoke([{"role": "user", "content": prompt}])
                data = parse_json(resp, {"case_domain": "unclear"})
                case_domain = data.get("case_domain", "unclear")
                if case_domain in CASE_SCHEMAS:
                    return case_domain
            except Exception:
                pass

        lowered = text.lower()
        scores = {
            domain: sum(1 for keyword in keywords if keyword.lower() in lowered)
            for domain, keywords in DOMAIN_KEYWORDS.items()
        }
        best_domain = max(scores, key=scores.get)
        return best_domain if scores[best_domain] > 0 else "unclear"


class CaseExtractor:
    def __init__(self, llm: Optional[Any] = None):
        self.llm = llm

    def extract(self, domain: str, text: str, current: Dict[str, Any]) -> Dict[str, Any]:
        schema = CASE_SCHEMAS[domain]
        fields = {**schema["required"], **schema["optional"]}

        if self.llm:
            field_list = ", ".join(fields.keys())
            prompt = (
                "你是法律案件信息抽取助手。"
                f"请从用户输入中提取这些字段：{field_list}。"
                "结合已有信息一起判断。仅返回 JSON，缺失字段填 null。\n\n"
                f"已有信息：{json.dumps(current, ensure_ascii=False)}\n"
                f"用户输入：{text}"
            )
            try:
                resp = self.llm.invoke([{"role": "user", "content": prompt}])
                fallback = {field: None for field in fields}
                return parse_json(resp, fallback)
            except Exception:
                pass

        return self._extract_by_rules(domain, text, current)

    def _extract_by_rules(self, domain: str, text: str, current: Dict[str, Any]) -> Dict[str, Any]:
        schema = CASE_SCHEMAS[domain]
        fields = {**schema["required"], **schema["optional"]}
        extracted = {field: None for field in fields}
        compact_text = summarize_text(text, 200)

        if not current.get("core_facts"):
            extracted["core_facts"] = compact_text

        goal_match = re.search(r"(想|希望|需要|打算)([^。；\n]{4,40})", text)
        if goal_match and not current.get("user_goal"):
            extracted["user_goal"] = goal_match.group(0).strip("，。； ")

        amount_match = re.search(r"((?:\d+(?:\.\d+)?)\s*(?:万|万元|元))", text)
        if amount_match and "amount_involved" in extracted:
            extracted["amount_involved"] = amount_match.group(1)

        if "contract_type" in extracted and not current.get("contract_type"):
            if "租" in text:
                extracted["contract_type"] = "租赁合同"
            elif "借款" in text or "借条" in text:
                extracted["contract_type"] = "借款合同"
            elif "买卖" in text:
                extracted["contract_type"] = "买卖合同"

        if "contract_counterparty" in extracted and not current.get("contract_counterparty"):
            counterparty_match = re.search(r"(房东|租客|公司|平台|商家|卖家|买家|甲方|乙方|对方)", text)
            if counterparty_match:
                extracted["contract_counterparty"] = counterparty_match.group(1)

        if "breach_fact" in extracted and not current.get("breach_fact"):
            breach = first_sentence_with_keyword(text, FIELD_KEYWORDS["breach_fact"])
            if breach:
                extracted["breach_fact"] = breach

        if "property_object" in extracted and not current.get("property_object"):
            prop = first_sentence_with_keyword(text, FIELD_KEYWORDS["property_object"])
            if prop:
                extracted["property_object"] = prop

        if "ownership_status" in extracted and not current.get("ownership_status"):
            ownership = first_sentence_with_keyword(text, FIELD_KEYWORDS["ownership_status"])
            if ownership:
                extracted["ownership_status"] = ownership

        if "dispute_behavior" in extracted and not current.get("dispute_behavior"):
            dispute = first_sentence_with_keyword(text, FIELD_KEYWORDS["dispute_behavior"])
            if dispute:
                extracted["dispute_behavior"] = dispute

        if "relationship_type" in extracted and not current.get("relationship_type"):
            relation_match = re.search(r"(夫妻|父母子女|同居关系|继承人之间|恋爱关系)", text)
            if relation_match:
                extracted["relationship_type"] = relation_match.group(1)

        if "current_status" in extracted and not current.get("current_status"):
            current_status = first_sentence_with_keyword(text, FIELD_KEYWORDS["current_status"])
            if current_status:
                extracted["current_status"] = current_status

        if "core_dispute" in extracted and not current.get("core_dispute"):
            core_dispute = first_sentence_with_keyword(text, FIELD_KEYWORDS["core_dispute"])
            if core_dispute:
                extracted["core_dispute"] = core_dispute

        if "children_info" in extracted and not current.get("children_info"):
            children_info = first_sentence_with_keyword(text, FIELD_KEYWORDS["children_info"])
            if children_info:
                extracted["children_info"] = children_info

        if "property_info" in extracted and not current.get("property_info"):
            property_info = first_sentence_with_keyword(text, FIELD_KEYWORDS["property_info"])
            if property_info:
                extracted["property_info"] = property_info

        if "evidence" in extracted and not current.get("evidence"):
            evidence = first_sentence_with_keyword(text, FIELD_KEYWORDS["evidence"])
            if evidence:
                extracted["evidence"] = evidence

        return extracted


class LegalAgent:
    def __init__(self, llm: Optional[Any] = None):
        self.llm = llm
        self.classifier = CaseClassifier(llm)
        self.extractor = CaseExtractor(llm)

    def init_state(self) -> Dict[str, Any]:
        return {
            "case_domain": None,
            "filled_slots": {},
            "history": [],
        }

    def run(self, text: str, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if state is None:
            state = self.init_state()

        state.setdefault("case_domain", None)
        state.setdefault("filled_slots", {})
        state.setdefault("history", [])
        state["history"].append({"role": "user", "content": text})

        if not state["case_domain"]:
            domain = self.classifier.classify(text)
            if domain == "unclear":
                return {
                    "status": "need_clarification",
                    "message": "我还不能准确判断案件类型，请说明更偏向合同、财产还是婚姻家庭纠纷。",
                    "state": state,
                }
            state["case_domain"] = domain

        domain = state["case_domain"]
        new_info = self.extractor.extract(domain, text, state["filled_slots"])
        state["filled_slots"] = merge(state["filled_slots"], new_info)

        schema = CASE_SCHEMAS[domain]
        missing = find_missing(state["filled_slots"], schema)

        if missing:
            return {
                "status": "need_more_info",
                "case_domain": domain,
                "questions": build_questions(missing),
                "state": state,
            }

        return {
            "status": "ok",
            "case_domain": domain,
            "summary": self._build_summary(domain, state["filled_slots"]),
            "state": state,
        }

    def _build_summary(self, domain: str, case_info: Dict[str, Any]) -> str:
        domain_label = {
            "contract": "合同纠纷",
            "property": "财产纠纷",
            "family": "婚姻家庭纠纷",
        }.get(domain, domain)
        facts = case_info.get("core_facts", "已收到案件描述")
        goal = case_info.get("user_goal", "等待进一步确认诉求")
        return f"当前识别为{domain_label}。核心事实：{facts}。用户目标：{goal}。"
