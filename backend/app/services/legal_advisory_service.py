from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Dict, List, Optional


CASE_EXAMPLES: List[Dict[str, Any]] = [
    {
        "title": "民间借贷到期未还本息纠纷",
        "case_domain": "contract",
        "keywords": ["借款", "到期未还", "利息", "转账记录", "催收"],
        "summary": "出借人提供借条、转账记录和催款聊天记录，主张借款人返还本金并支付利息。",
        "judgment_points": "在借贷关系明确、款项实际交付且已到期未还的情况下，法院通常支持返还本金及合理利息请求。",
        "court": "北京市朝阳区人民法院",
    },
    {
        "title": "房屋租赁合同提前解约纠纷",
        "case_domain": "contract",
        "keywords": ["租赁", "押金", "违约", "退租", "房东"],
        "summary": "承租人提前退租，出租人以违约为由拒绝返还押金并要求支付剩余租金。",
        "judgment_points": "需要结合合同解除条款、实际损失和双方履约情况判断违约责任范围。",
        "court": "上海市徐汇区人民法院",
    },
    {
        "title": "夫妻离婚后子女抚养权争议",
        "case_domain": "family",
        "keywords": ["离婚", "抚养权", "子女", "探望", "抚养费"],
        "summary": "双方围绕未成年子女抚养权归属、抚养费承担和探望安排产生争议。",
        "judgment_points": "法院通常以最有利于未成年子女原则综合判断抚养安排。",
        "court": "深圳市福田区人民法院",
    },
    {
        "title": "共同房产处分权属确认纠纷",
        "case_domain": "property",
        "keywords": ["房产", "共有", "过户", "处分", "产权登记"],
        "summary": "一方主张房屋属于共同共有，另一方未经同意擅自处分房产。",
        "judgment_points": "需结合产权登记、出资情况和共同共有关系判断处分行为效力。",
        "court": "杭州市西湖区人民法院",
    },
]


LAW_FIRMS: List[Dict[str, Any]] = [
    {
        "name": "北京市京衡律师事务所",
        "city": "北京",
        "district": "朝阳区",
        "address": "北京市朝阳区建国路88号 SOHO现代城附近",
        "near_subway": "地铁1号线、14号线 大望路站",
        "specialties": ["合同纠纷", "公司法务", "劳动争议"],
        "description": "靠近 CBD，适合企业法务咨询和商事争议处理。",
    },
    {
        "name": "北京市中诚律师事务所",
        "city": "北京",
        "district": "海淀区",
        "address": "北京市海淀区中关村南大街27号附近",
        "near_subway": "地铁4号线 魏公村站",
        "specialties": ["知识产权", "互联网纠纷", "民商事诉讼"],
        "description": "靠近高校和科技园，适合知识产权与互联网案件。",
    },
    {
        "name": "上海明理律师事务所",
        "city": "上海",
        "district": "徐汇区",
        "address": "上海市徐汇区漕溪北路398号附近",
        "near_subway": "地铁1号线、9号线 徐家汇站",
        "specialties": ["婚姻家事", "继承纠纷", "房产纠纷"],
        "description": "交通便利，适合婚姻家事及房产纠纷咨询。",
    },
    {
        "name": "上海申远律师事务所",
        "city": "上海",
        "district": "浦东新区",
        "address": "上海市浦东新区世纪大道100号附近",
        "near_subway": "地铁2号线 东昌路站",
        "specialties": ["金融纠纷", "股权争议", "企业合规"],
        "description": "位于陆家嘴商务区，适合金融和企业合规类需求。",
    },
    {
        "name": "广东南星律师事务所",
        "city": "深圳",
        "district": "南山区",
        "address": "深圳市南山区科技南十二路2号附近",
        "near_subway": "地铁9号线 深大南站",
        "specialties": ["创业融资", "股权架构", "知识产权"],
        "description": "靠近科技园，适合创业公司和科技企业。",
    },
    {
        "name": "广东鹏城律师事务所",
        "city": "深圳",
        "district": "福田区",
        "address": "深圳市福田区福华一路88号附近",
        "near_subway": "地铁1号线、4号线 会展中心站",
        "specialties": ["劳动争议", "合同纠纷", "商事仲裁"],
        "description": "位于中心商务区，适合商事谈判和劳动案件。",
    },
]


DOMAIN_TO_SPECIALTY = {
    "contract": ["合同纠纷", "商事仲裁", "公司法务"],
    "property": ["房产纠纷", "继承纠纷", "民商事诉讼"],
    "family": ["婚姻家事", "继承纠纷", "抚养纠纷"],
}


class LegalAdvisoryRepository:
    def __init__(self, sqlite_path: str = "law_demo.db"):
        self.sqlite_path = sqlite_path
        self._init_tables()
        self._seed_data()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self) -> None:
        conn = self._get_conn()
        cur = conn.cursor()

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS case_example (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                case_domain TEXT NOT NULL,
                keywords_json TEXT NOT NULL,
                summary TEXT NOT NULL,
                judgment_points TEXT NOT NULL,
                court TEXT
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS law_firm (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                city TEXT NOT NULL,
                district TEXT NOT NULL,
                address TEXT NOT NULL,
                near_subway TEXT,
                specialties_json TEXT NOT NULL,
                description TEXT
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis_record (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_domain TEXT,
                city TEXT,
                user_text TEXT NOT NULL,
                summary TEXT,
                payload_json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        conn.commit()
        conn.close()

    def _seed_data(self) -> None:
        conn = self._get_conn()
        cur = conn.cursor()

        case_count = cur.execute("SELECT COUNT(1) FROM case_example").fetchone()[0]
        if case_count == 0:
            cur.executemany(
                """
                INSERT INTO case_example
                (title, case_domain, keywords_json, summary, judgment_points, court)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item["title"],
                        item["case_domain"],
                        json.dumps(item["keywords"], ensure_ascii=False),
                        item["summary"],
                        item["judgment_points"],
                        item["court"],
                    )
                    for item in CASE_EXAMPLES
                ],
            )

        firm_count = cur.execute("SELECT COUNT(1) FROM law_firm").fetchone()[0]
        if firm_count == 0:
            cur.executemany(
                """
                INSERT INTO law_firm
                (name, city, district, address, near_subway, specialties_json, description)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item["name"],
                        item["city"],
                        item["district"],
                        item["address"],
                        item["near_subway"],
                        json.dumps(item["specialties"], ensure_ascii=False),
                        item["description"],
                    )
                    for item in LAW_FIRMS
                ],
            )

        conn.commit()
        conn.close()

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        candidates = re.findall(r"[\u4e00-\u9fff]{2,}", text or "")
        seen = []
        for token in candidates:
            if token not in seen:
                seen.append(token)
        return seen

    def search_cases(
        self,
        query: str,
        case_domain: Optional[str] = None,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        cur = conn.cursor()

        if case_domain:
            rows = cur.execute(
                """
                SELECT id, title, case_domain, keywords_json, summary, judgment_points, court
                FROM case_example
                WHERE case_domain = ?
                """,
                (case_domain,),
            ).fetchall()
        else:
            rows = cur.execute(
                """
                SELECT id, title, case_domain, keywords_json, summary, judgment_points, court
                FROM case_example
                """
            ).fetchall()
        conn.close()

        query_tokens = self._tokenize(query)
        ranked: List[Dict[str, Any]] = []
        for row in rows:
            keywords = json.loads(row["keywords_json"])
            haystack = " ".join(
                [row["title"], row["summary"], row["judgment_points"], " ".join(keywords)]
            )
            score = 0
            for token in query_tokens:
                if token in haystack:
                    score += 1
            if case_domain and row["case_domain"] == case_domain:
                score += 2
            if score == 0 and not query_tokens:
                score = 1
            if score > 0:
                ranked.append(
                    {
                        "id": row["id"],
                        "title": row["title"],
                        "case_domain": row["case_domain"],
                        "keywords": keywords,
                        "summary": row["summary"],
                        "judgment_points": row["judgment_points"],
                        "court": row["court"],
                        "score": score,
                    }
                )

        ranked.sort(key=lambda item: (-item["score"], item["title"]))
        return ranked[:top_k]

    def recommend_firms(
        self,
        city: Optional[str],
        case_domain: Optional[str],
        query: str,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        if not city:
            return []

        conn = self._get_conn()
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT id, name, city, district, address, near_subway, specialties_json, description
            FROM law_firm
            WHERE city = ?
            """,
            (city,),
        ).fetchall()
        conn.close()

        query_tokens = self._tokenize(query)
        preferred = DOMAIN_TO_SPECIALTY.get(case_domain or "", [])

        ranked: List[Dict[str, Any]] = []
        for row in rows:
            specialties = json.loads(row["specialties_json"])
            haystack = " ".join(specialties + [row["description"] or ""])
            score = 0
            for token in query_tokens:
                if token in haystack:
                    score += 1
            for tag in preferred:
                if tag in specialties:
                    score += 2
            ranked.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "city": row["city"],
                    "district": row["district"],
                    "address": row["address"],
                    "near_subway": row["near_subway"],
                    "specialties": specialties,
                    "description": row["description"],
                    "score": score or 1,
                }
            )

        ranked.sort(key=lambda item: (-item["score"], item["district"], item["name"]))
        return ranked[:top_k]

    def extract_city(self, text: str) -> Optional[str]:
        all_cities = sorted({item["city"] for item in LAW_FIRMS}, key=len, reverse=True)
        for city in all_cities:
            if city in (text or ""):
                return city
        return None

    def save_analysis_record(
        self,
        *,
        user_text: str,
        case_domain: Optional[str],
        city: Optional[str],
        summary: Optional[str],
        payload: Dict[str, Any],
    ) -> int:
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO analysis_record (case_domain, city, user_text, summary, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                case_domain,
                city,
                user_text,
                summary,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        record_id = cur.lastrowid
        conn.commit()
        conn.close()
        return record_id

    def list_analysis_records(self, limit: int = 20) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT id, case_domain, city, user_text, summary, payload_json, created_at
            FROM analysis_record
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        conn.close()

        return [
            {
                "id": row["id"],
                "case_domain": row["case_domain"],
                "city": row["city"],
                "user_text": row["user_text"],
                "summary": row["summary"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
