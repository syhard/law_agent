import os
import re
import json
import sqlite3
from typing import List, Dict, Any, Optional
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_settings
from services.llm_service import get_llm
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue


class LegalKnowledgeBase:
    def __init__(
        self,
        llm,
        sqlite_path: str = "law_kb.db",
        collection_name: str = "law_chunks",
        qdrant_url: Optional[str] = None,
        qdrant_api_key: Optional[str] = None,
        embedding_api_key: Optional[str] = None,
        embedding_base_url: Optional[str] = None,
        embedding_model: str = "text-embedding-v3",
    ):
        self.llm = llm
        self.sqlite_path = sqlite_path
        self.collection_name = collection_name

        self.qdrant_url = qdrant_url or os.getenv("QDRANT_URL")
        self.qdrant_api_key = qdrant_api_key or os.getenv("QDRANT_API_KEY")

        self.embedding_api_key = embedding_api_key or os.getenv("EMBED_API_KEY")
        self.embedding_base_url = embedding_base_url or os.getenv("EMBED_BASE_URL")
        self.embedding_model = embedding_model

        if not self.qdrant_url:
            raise ValueError("QDRANT_URL 未配置")
        if not self.embedding_api_key:
            raise ValueError("EMBED_API_KEY 未配置")

        self.qdrant = QdrantClient(
            url=self.qdrant_url,
            api_key=self.qdrant_api_key
        )

        self.embedding_client = OpenAI(
            api_key=self.embedding_api_key,
            base_url=self.embedding_base_url
        )

        self._init_sqlite()

    # =========================
    # SQLite 初始化
    # =========================
    def _get_conn(self):
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_sqlite(self):
        conn = self._get_conn()
        cur = conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS law_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_id INTEGER,
            level_type TEXT NOT NULL,          -- book / chapter
            title TEXT NOT NULL,
            full_path TEXT NOT NULL,
            sort_order INTEGER NOT NULL,
            article_start INTEGER,
            article_end INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(parent_id) REFERENCES law_catalog(id)
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS law_article (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            chapter_id INTEGER,
            article_no TEXT NOT NULL,
            article_num INTEGER NOT NULL,
            content TEXT NOT NULL,
            full_path TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(book_id) REFERENCES law_catalog(id),
            FOREIGN KEY(chapter_id) REFERENCES law_catalog(id)
        )
        """)

        cur.execute("CREATE INDEX IF NOT EXISTS idx_catalog_parent ON law_catalog(parent_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_catalog_level_type ON law_catalog(level_type)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_article_book_id ON law_article(book_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_article_chapter_id ON law_article(chapter_id)")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uk_article_num ON law_article(article_num)")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uk_catalog_path ON law_catalog(full_path)")

        conn.commit()
        conn.close()

    # =========================
    # Qdrant 初始化
    # =========================
    def _ensure_qdrant_collection(self, vector_size: int):
        collections = self.qdrant.get_collections().collections
        exists = any(c.name == self.collection_name for c in collections)
        if not exists:
            self.qdrant.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE)
            )
        self._ensure_qdrant_payload_indexes()

    def _ensure_qdrant_payload_indexes(self):
        """
        Create payload indexes required by Qdrant filters.
        Newer Qdrant setups may reject filtered search if the payload field
        has no index.
        """
        for field_name in ("book_id", "chapter_id", "article_num"):
            try:
                self.qdrant.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field_name,
                    field_schema="integer",
                )
            except Exception:
                # Ignore cases where the index already exists or the backend
                # treats repeated creation as an error.
                pass

    # =========================
    # Embedding
    # =========================
    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        batch_size = 10
        embeddings: List[List[float]] = []

        for start in range(0, len(texts), batch_size):
            batch = texts[start:start + batch_size]
            resp = self.embedding_client.embeddings.create(
                model=self.embedding_model,
                input=batch
            )
            embeddings.extend(item.embedding for item in resp.data)

        return embeddings

    # =========================
    # Markdown 解析
    # =========================
    @staticmethod
    def detect_level(title: str) -> str:
        if re.match(r"^第.+条", title):
            return "article"
        if "编" in title and "分编" not in title:
            return "book"
        if "章" in title:
            return "chapter"
        return "unknown"

    @staticmethod
    def chinese_to_int(text: str) -> Optional[int]:
        """
        将 '第五百七十七条' -> 577
        简化版，适合法条号。
        """
        m = re.match(r"^第(.+?)条$", text)
        if not m:
            return None

        cn = m.group(1)
        digits = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
        units = {"十": 10, "百": 100, "千": 1000}

        total = 0
        num = 0
        unit = 1

        i = len(cn) - 1
        while i >= 0:
            ch = cn[i]
            if ch in digits:
                num = digits[ch]
                total += num * unit
            elif ch in units:
                unit = units[ch]
                if i == 0:
                    total += unit
            i -= 1

        return total if total > 0 else None

    def parse_markdown(self, markdown_text: str) -> Dict[str, Any]:
        """
        只解析 编 / 章 / 条
        """
        lines = markdown_text.splitlines()

        books = []
        articles = []

        current_book = None
        current_chapter = None
        current_article_no = None
        current_article_content = []

        def flush_article():
            nonlocal current_article_no, current_article_content, current_book, current_chapter
            if current_article_no and current_article_content:
                content = "\n".join(current_article_content).strip()
                article_num = self.chinese_to_int(current_article_no)
                if article_num is not None:
                    full_path_parts = [p for p in [current_book, current_chapter, current_article_no] if p]
                    articles.append({
                        "book_title": current_book,
                        "chapter_title": current_chapter,
                        "article_no": current_article_no,
                        "article_num": article_num,
                        "content": content,
                        "full_path": " > ".join(full_path_parts),
                    })
            current_article_no = None
            current_article_content = []

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue

            heading_match = re.match(r"^(#+)\s+(.*)$", line)
            if heading_match:
                title = heading_match.group(2).strip()
                level = self.detect_level(title)

                if level in {"book", "chapter", "article"}:
                    flush_article()

                if level == "book":
                    current_book = title
                    current_chapter = None
                    books.append(title)
                elif level == "chapter":
                    current_chapter = title
                elif level == "article":
                    current_article_no = title
                continue

            if current_article_no:
                current_article_content.append(line)

        flush_article()

        return {
            "books": books,
            "articles": articles
        }

    # =========================
    # SQLite 写入（方案1：插入前判断）
    # =========================
    def _insert_catalog(
        self,
        cur,
        parent_id,
        level_type,
        title,
        full_path,
        sort_order,
        article_start=None,
        article_end=None
    ):
        """
        先按 full_path 查重，已存在则直接返回已有 id。
        """
        row = cur.execute("""
            SELECT id, article_start, article_end
            FROM law_catalog
            WHERE full_path = ?
            LIMIT 1
        """, (full_path,)).fetchone()

        if row:
            existing_id = row["id"]

            # 如有更完整的条文范围，顺手更新一下
            if article_start is not None and article_end is not None:
                new_start = article_start
                new_end = article_end

                old_start = row["article_start"]
                old_end = row["article_end"]

                if old_start is not None:
                    new_start = min(old_start, article_start)
                if old_end is not None:
                    new_end = max(old_end, article_end)

                cur.execute("""
                    UPDATE law_catalog
                    SET article_start = ?, article_end = ?
                    WHERE id = ?
                """, (new_start, new_end, existing_id))

            return existing_id

        cur.execute("""
            INSERT INTO law_catalog (parent_id, level_type, title, full_path, sort_order, article_start, article_end)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (parent_id, level_type, title, full_path, sort_order, article_start, article_end))
        return cur.lastrowid

    def _insert_article(self, cur, book_id, chapter_id, article_no, article_num, content, full_path):
        """
        先按 article_num 查重，已存在则返回已有 id。
        这是你当前单法规场景下最直接的方案。
        """
        row = cur.execute("""
            SELECT id
            FROM law_article
            WHERE article_num = ?
            LIMIT 1
        """, (article_num,)).fetchone()

        if row:
            return row["id"]

        cur.execute("""
            INSERT INTO law_article (book_id, chapter_id, article_no, article_num, content, full_path)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (book_id, chapter_id, article_no, article_num, content, full_path))
        return cur.lastrowid

    def _find_article_id_by_num(self, cur, article_num: int) -> Optional[int]:
        row = cur.execute("""
            SELECT id
            FROM law_article
            WHERE article_num = ?
            LIMIT 1
        """, (article_num,)).fetchone()
        return row["id"] if row else None

    def add_markdown_document(self, markdown_text: str):
        """
        解析 markdown -> SQLite + Qdrant
        """
        parsed = self.parse_markdown(markdown_text)
        articles = parsed["articles"]
        if not articles:
            raise ValueError("未从 markdown 中解析到任何条文，请检查标题格式")

        conn = self._get_conn()
        cur = conn.cursor()

        # 先按 book / chapter 分组
        book_map = {}
        chapter_map = {}
        sort_order = 1

        grouped: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        for art in articles:
            grouped.setdefault(art["book_title"], {})
            grouped[art["book_title"]].setdefault(art["chapter_title"], [])
            grouped[art["book_title"]][art["chapter_title"]].append(art)

        # 建目录
        for book_title, chapters in grouped.items():
            all_nums = [a["article_num"] for ch in chapters.values() for a in ch]
            book_id = self._insert_catalog(
                cur=cur,
                parent_id=None,
                level_type="book",
                title=book_title,
                full_path=book_title,
                sort_order=sort_order,
                article_start=min(all_nums),
                article_end=max(all_nums),
            )
            sort_order += 1
            book_map[book_title] = book_id

            for chapter_title, ch_articles in chapters.items():
                nums = [a["article_num"] for a in ch_articles]
                full_path = f"{book_title} > {chapter_title}"
                chapter_id = self._insert_catalog(
                    cur=cur,
                    parent_id=book_id,
                    level_type="chapter",
                    title=chapter_title,
                    full_path=full_path,
                    sort_order=sort_order,
                    article_start=min(nums),
                    article_end=max(nums),
                )
                sort_order += 1
                chapter_map[(book_title, chapter_title)] = chapter_id

        # 建 article + 准备 chunk
        chunk_records = []
        duplicate_count = 0
        duplicate_articles = []
        for art in articles:
            book_id = book_map[art["book_title"]]
            chapter_id = chapter_map[(art["book_title"], art["chapter_title"])]

            existing_article_id = self._find_article_id_by_num(cur, art["article_num"])
            if existing_article_id is not None:
                duplicate_count += 1
                duplicate_articles.append(art["article_no"])
                continue

            article_id = self._insert_article(
                cur=cur,
                book_id=book_id,
                chapter_id=chapter_id,
                article_no=art["article_no"],
                article_num=art["article_num"],
                content=art["content"],
                full_path=art["full_path"]
            )

            chunk_text = f"{art['article_no']}\n{art['content']}"
            chunk_records.append({
                "article_id": article_id,
                "book_id": book_id,
                "chapter_id": chapter_id,
                "article_no": art["article_no"],
                "article_num": art["article_num"],
                "full_path": art["full_path"],
                "chunk_text": chunk_text
            })

        conn.commit()
        conn.close()

        if chunk_records:
            # 写入 Qdrant（同 article_id 会自动 upsert 覆盖）
            vectors = self.embed_texts([x["chunk_text"] for x in chunk_records])
            self._ensure_qdrant_collection(vector_size=len(vectors[0]))

            points = []
            for rec, vec in zip(chunk_records, vectors):
                points.append(
                    PointStruct(
                        id=rec["article_id"],
                        vector=vec,
                        payload={
                            "article_id": rec["article_id"],
                            "book_id": rec["book_id"],
                            "chapter_id": rec["chapter_id"],
                            "article_no": rec["article_no"],
                            "article_num": rec["article_num"],
                            "chunk_type": "article",
                            "full_path": rec["full_path"],
                        }
                    )
                )

            self.qdrant.upsert(
                collection_name=self.collection_name,
                points=points
            )

        result = {
            "message": "文档导入完成",
            "article_count": len(chunk_records),
            "duplicate_count": duplicate_count,
        }
        if duplicate_count > 0:
            duplicate_preview = "、".join(duplicate_articles[:5])
            result["warning"] = (
                f"检测到 {duplicate_count} 条重复条文，已自动跳过不再写入。"
                f"示例：{duplicate_preview}"
            )
        return result

    # =========================
    # SQLite 查询辅助
    # =========================
    def get_book_id_by_title_keyword(self, keyword: str) -> Optional[int]:
        conn = self._get_conn()
        cur = conn.cursor()
        row = cur.execute("""
            SELECT id FROM law_catalog
            WHERE level_type = 'book' AND title LIKE ?
            LIMIT 1
        """, (f"%{keyword}%",)).fetchone()
        conn.close()
        return row["id"] if row else None

    def get_chapter_id_by_title_keyword(self, book_id: int, keyword: str) -> Optional[int]:
        conn = self._get_conn()
        cur = conn.cursor()
        row = cur.execute("""
            SELECT id FROM law_catalog
            WHERE level_type = 'chapter'
              AND parent_id = ?
              AND title LIKE ?
            LIMIT 1
        """, (book_id, f"%{keyword}%")).fetchone()
        conn.close()
        return row["id"] if row else None

    def get_article_by_id(self, article_id: int) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        cur = conn.cursor()
        row = cur.execute("""
            SELECT id, article_no, article_num, content, full_path
            FROM law_article
            WHERE id = ?
        """, (article_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def _prompt_mqe(self, query: str, n: int = 3) -> List[str]:
        """
        Use LLM to generate diverse but relevant query rewrites.
        Falls back to the original query if LLM is unavailable.
        """
        if not self.llm:
            return [query]

        prompt = [
            {
                "role": "system",
                "content": (
                    "你是法律检索查询扩展助手。"
                    "请基于用户问题生成语义等价或互补的多样化查询。"
                    "使用中文，简短，不要解释，不要编号，每行一个查询。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"原始查询：{query}\n"
                    f"请给出{n}个不同表述的检索查询，每行一个。"
                ),
            },
        ]

        try:
            text = self.llm.invoke(prompt)
            lines = [ln.strip("- \t0123456789.、") for ln in (text or "").splitlines()]
            seen = {query.strip()}
            queries = []
            for line in lines:
                candidate = line.strip()
                if not candidate or candidate in seen:
                    continue
                seen.add(candidate)
                queries.append(candidate)
                if len(queries) >= n:
                    break
            return queries or [query]
        except Exception:
            return [query]

    def _prompt_hyde(self, query: str) -> Optional[str]:
        """
        Generate a hypothetical answer paragraph for retrieval.
        """
        if not self.llm:
            return None

        prompt = [
            {
                "role": "system",
                "content": (
                    "你是法律检索假设文档生成助手。"
                    "请根据用户问题，直接写一段可能出现在法条解释或法律分析中的客观段落，"
                    "用于向量检索。不要写分析过程，不要分点。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"问题：{query}\n"
                    "请直接生成一段中等长度、客观、包含关键法律术语的中文段落。"
                ),
            },
        ]

        try:
            text = self.llm.invoke(prompt)
            return (text or "").strip() or None
        except Exception:
            return None

    def _qdrant_search(
        self,
        query_vector: List[float],
        top_k: int,
        q_filter: Optional[Filter] = None,
    ):
        """
        Compatible with both old and new qdrant-client APIs.
        """
        if hasattr(self.qdrant, "search"):
            return self.qdrant.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                query_filter=q_filter,
                limit=top_k,
                with_payload=True,
                with_vectors=False,
            )

        if hasattr(self.qdrant, "query_points"):
            response = self.qdrant.query_points(
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

    def _build_query_filter(
        self,
        book_id: Optional[int] = None,
        chapter_id: Optional[int] = None,
    ) -> Optional[Filter]:
        conditions = []
        if book_id is not None:
            conditions.append(
                FieldCondition(key="book_id", match=MatchValue(value=book_id))
            )
        if chapter_id is not None:
            conditions.append(
                FieldCondition(key="chapter_id", match=MatchValue(value=chapter_id))
            )
        return Filter(must=conditions) if conditions else None

    def _search_once(
        self,
        query_text: str,
        top_k: int,
        q_filter: Optional[Filter] = None,
        source: str = "original",
    ) -> List[Dict[str, Any]]:
        query_vector = self.embed_texts([query_text])[0]
        hits = self._qdrant_search(
            query_vector=query_vector,
            top_k=top_k,
            q_filter=q_filter,
        )

        results = []
        for hit in hits:
            payload = getattr(hit, "payload", None) or {}
            score = getattr(hit, "score", None)
            article_id = payload.get("article_id")
            if article_id is None:
                continue
            article = self.get_article_by_id(article_id)
            if article:
                results.append({
                    "score": score,
                    "article_id": article["id"],
                    "article_no": article["article_no"],
                    "article_num": article["article_num"],
                    "full_path": article["full_path"],
                    "content": article["content"],
                    "query_used": query_text,
                    "query_source": source,
                })
        return results

    @staticmethod
    def _merge_ranked_results(results: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
        merged: Dict[int, Dict[str, Any]] = {}
        for item in results:
            article_id = item["article_id"]
            existing = merged.get(article_id)
            if existing is None or (item.get("score") or 0) > (existing.get("score") or 0):
                merged[article_id] = item

        ranked = sorted(
            merged.values(),
            key=lambda x: x.get("score") if x.get("score") is not None else float("-inf"),
            reverse=True,
        )
        return ranked[:top_k]

    # =========================
    # 检索
    # =========================
    def search(
        self,
        query: str,
        top_k: int = 5,
        book_id: Optional[int] = None,
        chapter_id: Optional[int] = None,
        enable_mqe: bool = False,
        mqe_count: int = 3,
        enable_hyde: bool = False,
    ) -> List[Dict[str, Any]]:
        self._ensure_qdrant_payload_indexes()
        q_filter = self._build_query_filter(book_id=book_id, chapter_id=chapter_id)

        search_jobs = [(query, "original")]

        if enable_mqe:
            for expanded_query in self._prompt_mqe(query, n=mqe_count):
                if expanded_query != query:
                    search_jobs.append((expanded_query, "mqe"))

        if enable_hyde:
            hyde_query = self._prompt_hyde(query)
            if hyde_query:
                search_jobs.append((hyde_query, "hyde"))

        all_results = []
        for query_text, source in search_jobs:
            all_results.extend(
                self._search_once(
                    query_text=query_text,
                    top_k=top_k,
                    q_filter=q_filter,
                    source=source,
                )
            )

        return self._merge_ranked_results(all_results, top_k=top_k)


if __name__ == "__main__":
    settings = get_settings()
    llm = get_llm()
    kb = LegalKnowledgeBase(
        llm=llm,
        sqlite_path="law_demo.db",
        collection_name="law_demo_chunks",
        qdrant_url=os.getenv("QDRANT_URL"),
        qdrant_api_key=os.getenv("QDRANT_API_KEY"),
        embedding_api_key=os.getenv("EMBED_API_KEY"),
        embedding_base_url=os.getenv("EMBED_BASE_URL"),
        embedding_model="text-embedding-v3",
    )

    md_file_path = os.path.join("law", "民法典_最终正确版.md")
    with open(md_file_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    # 1. 添加 markdown 文档（可重复执行，重复条文会给出 warning）
    add_result = kb.add_markdown_document(md_text)
    print("添加结果：")
    print(json.dumps(add_result, ensure_ascii=False, indent=2))

    # 2. 先从 SQLite 找到“合同编”
    contract_book_id = kb.get_book_id_by_title_keyword("合同")
    print("\n合同编 book_id:", contract_book_id)

    # 3. 再找“违约责任”这一章
    breach_chapter_id = kb.get_chapter_id_by_title_keyword(contract_book_id, "违约责任")
    print("违约责任 chapter_id:", breach_chapter_id)

    # 4. 查询案例：限定在合同编 / 违约责任章
    query = "借款到期不还，应该承担什么责任"
    results = kb.search(
        query=query,
        top_k=3,
        book_id=contract_book_id,
        chapter_id=breach_chapter_id
    )

    print("\n查询结果：")
    print(json.dumps(results, ensure_ascii=False, indent=2))
