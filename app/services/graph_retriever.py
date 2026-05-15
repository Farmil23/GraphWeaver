import re
import time
from typing import TypedDict, List, Optional
from langchain_core.prompts import ChatPromptTemplate
from langchain_neo4j import Neo4jGraph
from app.core.config import settings
from app.services.graph_extractor import NodeType, RelationType
from app.services.llm_service import GroqClient
from app.services.graph_extractor import ExtractionResult, GraphExtractorService
from app.db.neo4j_client import Neo4jClient
from app.core.logging import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)

# ── Schema cache (refresh every 5 minutes) ────────────────────────────────────
_SCHEMA_CACHE: dict = {}
_SCHEMA_TTL   = 300   # seconds

# 1. Definisi State agar data mengalir dengan konsisten
class AgentState(TypedDict):
    question: str
    cypher_query: Optional[str]
    graph_context: Optional[str]
    answer: Optional[str]
    query_decomposition : str
    query_advice : str

class GraphRetrieverService:
    def __init__(self):
        # Lazy Neo4j connection — don't crash app startup if AuraDB is paused
        self._graph: Optional[Neo4jGraph] = None

        # LLM untuk generate Cypher
        groq_client = GroqClient()
        self.llm = groq_client.get_llm()

    @property
    def graph(self) -> Neo4jGraph:
        """Connect on first use so the app starts even if Neo4j is temporarily down."""
        if self._graph is None:
            logger.info("Connecting to Neo4j AuraDB...")
            self._graph = Neo4jGraph(
                url=settings.NEO4J_URI,
                username=settings.NEO4J_USERNAME,
                password=settings.NEO4J_PASSWORD,
                database=settings.NEO4J_DATABASE,
            )
            logger.info("Neo4j connected successfully.")
        return self._graph

    def _get_live_schema(self) -> dict:
        """Query actual labels and rel types from Neo4j — cached for 5 minutes."""
        global _SCHEMA_CACHE
        now = time.time()

        if _SCHEMA_CACHE.get("ts", 0) + _SCHEMA_TTL > now:
            return _SCHEMA_CACHE["data"]

        _DEFAULT = {
            "labels":    ["Person", "Company", "Address", "Document"],
            "rel_types": ["DIRECTOR_OF", "WORKS_AT", "OWNS_SHARE", "TRANSFERRED_TO",
                          "REGISTERED_AT", "LIVES_AT", "FAMILY_OF", "MARRIED_TO",
                          "USES_EMAIL", "BENEFICIAL_OWNER_OF", "MENTIONED_IN"],
        }
        try:
            labels    = [r["label"] for r in
                         self.graph.query("CALL db.labels() YIELD label RETURN label")]
            rel_types = [r["relationshipType"] for r in
                         self.graph.query("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType")]
            data = {
                "labels":    labels    or _DEFAULT["labels"],
                "rel_types": rel_types or _DEFAULT["rel_types"],
            }
        except Exception:
            data = _DEFAULT

        _SCHEMA_CACHE = {"ts": now, "data": data}
        logger.info(f"Schema refreshed: {len(data['labels'])} labels, {len(data['rel_types'])} rel types")
        return data

    def _get_system_prompt(self):
        schema = self._get_live_schema()
        labels    = schema["labels"]
        rel_types = schema["rel_types"]

        return f"""
        Kamu adalah AI Investigator Forensik Elit dan pakar Neo4j Cypher.
        Tugasmu: Ubah pertanyaan user menjadi satu query Cypher yang valid dan bisa dieksekusi.

        SKEMA DATABASE (LIVE):
        - Node Labels   : {labels}
        - Relation Types: {rel_types}
        - Properti Node : id, name, name_normalized, type, context
        - Properti Rel  : details

        ═══ ATURAN WAJIB ═══
        1. SELALU gunakan CONTAINS untuk pencarian nama — JANGAN exact match.
           BENAR : WHERE toLower(n.name) CONTAINS toLower("nebula")
           SALAH : WHERE n.name = "PT Nebula Nusantara"

        2. SETIAP variabel yang dipakai di RETURN HARUS sudah didefinisikan di MATCH/OPTIONAL MATCH.
           BENAR : MATCH (p)-[r]->(c) RETURN p.name, r.details, c.name
           SALAH : MATCH (p)-[:DIRECTOR_OF]->(c) RETURN p.name, r.details  ← r tidak didefinisikan!

        3. Kalau relasi tidak perlu propertinya, gunakan anonymous: MATCH (p)-[:DIRECTOR_OF]->(c)
           Kalau butuh properti relasi, wajib bind: MATCH (p)-[r:DIRECTOR_OF]->(c) RETURN r.details

        4. Gunakan OPTIONAL MATCH untuk relasi tambahan.

        5. Kembalikan HANYA Cypher murni — TANPA markdown, TANPA ```cypher, TANPA komentar //.

        6. DILARANG KERAS: size((pattern)) — ini TIDAK VALID di Neo4j 5!
           SALAH : WHERE size((c)<-[:DIRECTOR_OF]-()) > 0
           BENAR : WHERE COUNT {{ (c)<-[:DIRECTOR_OF]-() }} > 0
           Atau lebih baik: gunakan EXISTS {{ MATCH (c)<-[:DIRECTOR_OF]-() }}

        7. DILARANG: type(var)-[:REL]->(other) di dalam RETURN
           type() hanya menerima bound relationship variable: type(r) bukan type(p)-[:R]->(q)

        ═══ POLA QUERY YANG BENAR ═══

        // Semua koneksi node dengan properti relasi:
        MATCH (p) WHERE toLower(p.name) CONTAINS toLower("nebula")
        OPTIONAL MATCH (p)-[r]->(x)
        OPTIONAL MATCH (y)-[r2]->(p)
        RETURN p.name AS entity, p.context AS context, labels(p)[0] AS type,
               type(r) AS rel_out, r.details AS rel_details, x.name AS connected_to,
               type(r2) AS rel_in, y.name AS connected_from
        LIMIT 50

        // Direktur sebuah perusahaan:
        MATCH (p:Person)-[r:DIRECTOR_OF]->(c:Company)
        WHERE toLower(c.name) CONTAINS toLower("nebula")
        RETURN p.name AS director, p.context AS role, r.details AS details, c.name AS company

        // Beneficial ownership chain:
        MATCH (p:Person)-[r:BENEFICIAL_OWNER_OF|OWNS_SHARE]->(c)
        WHERE toLower(p.name) CONTAINS toLower("hartono")
        RETURN p.name, type(r) AS ownership_type, r.details, c.name, c.context

        // Lokasi / alamat perusahaan — gunakan REGISTERED_AT atau LIVES_AT:
        MATCH (c:Company)-[r:REGISTERED_AT]->(a)
        OPTIONAL MATCH (c)<-[:DIRECTOR_OF|OWNS_SHARE]-(p)
        RETURN c.name AS company, c.context AS info, a.name AS location, a.context AS address_detail,
               collect(DISTINCT p.name) AS connected_persons
        LIMIT 30

        // Kalau tidak ada nama spesifik, lihat SEMUA entitas dan relasinya:
        MATCH (n)
        OPTIONAL MATCH (n)-[r]->(m)
        RETURN labels(n)[0] AS type, n.name AS entity, n.context AS context,
               type(r) AS rel, m.name AS connected
        LIMIT 60

        // Aliran keuangan:
        MATCH (src)-[r:TRANSFERRED_TO|PAYS_DEBT_TO|LENDS_TO|BORROWS_FROM]->(dst)
        RETURN src.name AS from_entity, type(r) AS flow_type, r.details AS amount, dst.name AS to_entity
        LIMIT 30
        """

    def _get_query_decomposition(self, state: AgentState):
        schema    = self._get_live_schema()
        labels    = schema["labels"]
        rel_types = schema["rel_types"]
        saran     = state.get("query_advice", "")

        saran_block = f"\nSARAN TAMBAHAN DARI USER:\n{saran}\n" if saran else ""

        return f"""
        Kamu adalah AI Investigator Forensik yang menganalisis pertanyaan user
        dan merencanakan strategi pencarian di Knowledge Graph.

        SKEMA DATABASE (LIVE):
        - Node Labels   : {labels}
        - Relation Types: {rel_types}
        - Properti      : id, name, name_normalized, context, details
        {saran_block}
        TUGASMU:
        Uraikan pertanyaan user menjadi rencana pencarian yang jelas:
        1. Entitas apa yang perlu dicari?
        2. Relasi apa yang relevan?
        3. Apakah perlu mencari path / chain kepemilikan?
        4. Apakah ada risiko duplikat nama yang perlu dipertimbangkan?

        CONTOH OUTPUT:
        Pertanyaan: "siapa yang mengendalikan PT Nebula?"
        Rencana:
          - Cari node Company dengan name CONTAINS "Nebula"
          - Temukan semua Person yang terhubung via DIRECTOR_OF, OWNS_SHARE, BENEFICIAL_OWNER_OF
          - Telusuri kepemilikan berlapis (depth 1-3)
          - Cek apakah ada alamat / email bersama (USES_EMAIL, REGISTERED_AT)

        ATURAN:
        - Gunakan nama dengan Title Case (misal: Budi Santoso, PT Maju Jaya)
        - Jangan sebut node yang tidak ada di schema
        - Output harus mudah dimengerti oleh agent Cypher writer
        """
        
    def generate_cypher(self, state: AgentState):
        from langchain_core.messages import SystemMessage, HumanMessage
        
        system_content = self._get_system_prompt()
        
        messages = [
            SystemMessage(content=system_content),
            HumanMessage(content=f"Pertanyaan: {state['query_decomposition']}")
        ]
        
        # Eksekusi model
        response = self.llm.invoke(messages)
        logger.info(f"✅ LLM Menghasilkan Response")
        
        
        # Pembersihan teks tambahan jika LLM tetap bandel memberikan markdown
        clean_query = response.content.strip()
        if "```" in clean_query:
            clean_query = clean_query.split("```")[1]
            if clean_query.startswith("cypher"):
                clean_query = clean_query[6:]
        
        clean_query = clean_query.strip()
        logger.info(f"🔍 Generated Cypher query: {clean_query}") # Debugging
        
        return {**state, "cypher_query": clean_query}

    def query_decomposition(self, state: AgentState):
        from langchain_core.messages import SystemMessage, HumanMessage

        system_content = self._get_query_decomposition(state)

        messages = [
            SystemMessage(content=system_content),
            HumanMessage(content=f"Pertanyaan: {state['question']}")
        ]
        
        # Eksekusi model
        response = self.llm.invoke(messages)
        logger.info(f"✅ Decomposition Menghasilkan Response")
        
        clean_query = response.content.strip()
    
        clean_query = clean_query.strip()
        logger.info(f"🔍 Generated Query: {clean_query}") # Debugging
        
        return {**state, "query_decomposition": clean_query}
    
    def execute_query(self, state: AgentState):
        """Execute the LLM-generated Cypher and store rich context."""
        query = state.get("cypher_query", "").strip()
        question = state.get("question", "")

        if not query or query.lower().startswith("error"):
            logger.warning("Invalid or empty Cypher — using fallback query")
            fallback = self._fallback_query(question)
            return {**state, "graph_context": str(fallback) if fallback else "[]"}

        # Strip markdown fences if LLM still wraps them
        if "```" in query:
            parts = query.split("```")
            query = parts[1] if len(parts) > 1 else parts[0]
            if query.lower().startswith("cypher"):
                query = query[6:]
            query = query.strip()

        # Auto-fix: if RETURN contains 'r.' but 'r' is not bound, strip those references
        query = self._sanitize_cypher(query)

        try:
            results = self.graph.query(query)
            logger.info(f"Query returned {len(results)} rows")

            if not results:
                # Fallback: broad search using name fragments from question
                logger.info("No results — trying fallback broad search")
                fallback = self._fallback_query(question)
                if fallback:
                    logger.info(f"Fallback returned {len(fallback)} rows")
                    return {**state, "graph_context": str(fallback)}

            return {**state, "graph_context": str(results) if results else "[]"}

        except Exception as e:
            logger.error(f"Query execution error: {e} | Query: {query[:200]}")
            # On any Cypher error: use fallback broad search, never expose error to LLM
            fallback = self._fallback_query(question)
            if fallback:
                logger.info(f"Error fallback returned {len(fallback)} rows")
                return {**state, "graph_context": str(fallback)}
            return {**state, "graph_context": "[]"}

    def _sanitize_cypher(self, query: str) -> str:
        """
        Heuristic fixes for common LLM Cypher generation mistakes:
        1. Remove RETURN references to undefined relationship variable 'r' (r.prop).
        2. Remove invalid type(var)-[:REL]->(other) path patterns in RETURN — these
           are a hallucination where the LLM conflates type() with a pattern expression.
        3. Strip trailing commas left by item removal.
        """
        import re as _re

        # ── Fix 1: undefined 'r' variable in RETURN ─────────────────────────────
        has_r_binding   = bool(_re.search(r'-\[r[0-9]?\s*[:\|]?', query, _re.IGNORECASE))
        has_r_in_return = bool(_re.search(r'\bRETURN\b.*\br\.', query, _re.IGNORECASE | _re.DOTALL))
        if has_r_in_return and not has_r_binding:
            query = _re.sub(r',?\s*r\d?\.[\w]+(\s+AS\s+\w+)?', '', query, flags=_re.IGNORECASE)
            logger.warning("Auto-sanitized undefined 'r' variable in RETURN clause")

        # ── Fix 2: type(var)-[:REL]->(other) hallucination in RETURN ────────────
        # Pattern: type(something)-[:ANYTHING]->(something) [AS alias]
        # This is not valid Cypher — type() only accepts a bound relationship var.
        # Remove the whole token (including leading comma / whitespace).
        invalid_type_pattern = _re.compile(
            r',?\s*type\s*\([^)]+\)\s*-\[:[^\]]+\]->\s*\([^)]*\)\s*(?:AS\s+\w+)?',
            _re.IGNORECASE,
        )
        if invalid_type_pattern.search(query):
            query = invalid_type_pattern.sub('', query)
            logger.warning("Auto-sanitized invalid type(var)-[:REL]->() pattern in RETURN clause")

        # ── Fix 3: trailing / double commas in RETURN after removals ─────────────
        query = _re.sub(r',\s*,', ',', query)
        query = _re.sub(r',\s*(LIMIT|ORDER|SKIP|UNION)', r' \1', query, flags=_re.IGNORECASE)
        query = _re.sub(r'(RETURN|WITH)\s*,', r'\1 ', query, flags=_re.IGNORECASE)

        # ── Fix 4: size((pattern)) → COUNT { (pattern) } (Neo4j 5 syntax) ────────
        # Neo4j 5 removed support for size() with pattern expressions.
        # Convert: size((n)-[:REL]->()) → COUNT { (n)-[:REL]->() }
        size_pattern = _re.compile(
            r'\bsize\s*\(\s*(\([^)]*\)(?:\s*<?-\[:[^\]]+\]-?>?\s*\([^)]*\))*)\s*\)',
            _re.IGNORECASE,
        )
        if size_pattern.search(query):
            query = size_pattern.sub(lambda m: f'COUNT {{ {m.group(1)} }}', query)
            logger.warning("Auto-fixed size(pattern) → COUNT { pattern } for Neo4j 5 compatibility")

        return query.strip()

    # Common Indonesian/English stop words — words that are NOT entity names
    _STOP_WORDS = {
        # Pronouns / question words
        "siapa", "yang", "apa", "dari", "dengan", "untuk", "dalam", "pada",
        "adalah", "ada", "dan", "atau", "juga", "telah", "akan", "sudah",
        "tidak", "bukan", "oleh", "kepada", "tentang", "antara", "serta",
        "bagaimana", "dimana", "berapa", "kapan", "kenapa", "mengapa",
        "semua", "setiap", "para", "jajaran", "direksi", "komisaris",
        "perusahaan", "badan", "entitas", "lain", "mereka",
        "hubungan", "relasi", "koneksi", "terkait", "berkaitan",
        "the", "and", "or", "who", "what", "where", "how", "why",
        "list", "show", "find", "get", "tell", "give", "know",
        # Location / description words — not entity names
        "lokasi", "basis", "operasional", "cangkang", "terlibat", "mana",
        "di", "ke", "di", "ter", "ber", "me", "pe",
        "alamat", "tempat", "wilayah", "daerah", "kota", "negara",
        "kantor", "pusat", "cabang", "sektor", "bidang", "industri",
        "laporan", "dokumen", "berkas", "file", "data", "informasi",
        "analisis", "investigasi", "skandal", "kasus", "masalah",
        "direktur", "komisaris", "pemegang", "saham", "kepemilikan",
        "berdasarkan", "menurut", "sesuai", "terkait", "berhubungan",
        "jelaskan", "sebutkan", "identifikasi", "temukan", "cari",
        "bagaimana", "mengapa", "apakah", "apabila", "ketika",
        "jaringan", "struktur", "aliran", "transfer", "transaksi",
    }

    # Minimum number of rows from keyword search to be considered "useful context"
    _MIN_USEFUL_ROWS = 5

    def _fallback_query(self, question: str) -> list:
        """
        Broad MATCH fallback with two-tier strategy:
        1. Keyword search on entity names (Title Case proper nouns preferred)
        2. If keyword search found < _MIN_USEFUL_ROWS, ALWAYS supplement with all-nodes query
           This handles questions where no entity name appears (e.g. "Di mana lokasi cangkang?")
        """
        q_all = """
        MATCH (n)
        WHERE NOT (n.name IS NULL OR n.name = '')
        OPTIONAL MATCH (n)-[r]->(m)
        RETURN labels(n)[0] AS node_label, n.name AS entity, n.context AS context,
               type(r) AS rel, r.details AS rel_details,
               m.name AS connected, m.context AS connected_context
        ORDER BY node_label
        LIMIT 80
        """

        try:
            raw_words = re.sub(r'[^\w\s]', '', question).split()

            # 1st priority: Title Case words that are likely proper nouns / entity names
            proper  = [w for w in raw_words
                       if len(w) > 2 and w[0].isupper()
                       and w.lower() not in self._STOP_WORDS]
            # 2nd priority: long lowercase words not in stop list
            general = [w for w in raw_words
                       if len(w) > 5 and w.lower() not in self._STOP_WORDS
                       and w not in proper]

            keywords = (proper + general)[:5]

            keyword_results = []
            if keywords:
                contains_clause = " OR ".join(
                    f'toLower(n.name) CONTAINS toLower("{w}")' for w in keywords
                )
                q_kw = f"""
                MATCH (n) WHERE {contains_clause}
                OPTIONAL MATCH (n)-[r]->(m)
                RETURN labels(n)[0] AS node_label, n.name AS entity, n.context AS context,
                       type(r) AS rel, r.details AS rel_details,
                       m.name AS connected, m.context AS connected_context
                LIMIT 50
                """
                keyword_results = self.graph.query(q_kw)
                logger.info(f"Fallback keyword search found {len(keyword_results)} rows for: {keywords}")

            # If keyword search gave useful results, return them
            if len(keyword_results) >= self._MIN_USEFUL_ROWS:
                return keyword_results

            # Not enough specific results — always return full graph context
            # so the LLM can scan all entities for the answer
            logger.info(
                f"Fallback: {'keyword rows < threshold' if keyword_results else 'no keywords matched'}"
                " — returning full graph snapshot"
            )
            all_results = self.graph.query(q_all)

            # Merge: put keyword results first (more relevant), then broad context
            seen = {r.get("entity") for r in keyword_results}
            merged = list(keyword_results)
            for row in all_results:
                if row.get("entity") not in seen:
                    merged.append(row)
                    seen.add(row.get("entity"))

            logger.info(f"Fallback merged result: {len(merged)} rows")
            return merged

        except Exception as exc:
            logger.error(f"Fallback query error: {exc}")
            return []

    def route_rewrite_query_cypher(self, state: AgentState):

            graph_context = state.get("graph_context", "")
            SYSTEM_PROMPT = """
                kamu adalah seorang AI Detektif yang bekerja sama dengan hasil Node dan context dari data Graph.
                kamu nantinya akan mendapatkan context utama dari graph dan kamu diwajibkan menjawab pertanyaan secara formal dan juga memiliki makna tersendiri.
                JIKA MISALKAN CONTEXT YANG DIDAPAT BERNILAI KOSONG KELUARKAN = "draft kosong" NAMUN JIKA MISALKAN CONTEXT GRAPH UDAH SESUAI MAKA KELUARKAN = "answer_user"
            """
            
            prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("human", "Pertanyaan: {question}\n Data Graf: {context}")
            ])
            
            chain = prompt | self.llm
            response = chain.invoke({"question": state["question"], "context": graph_context})
            
            print("DEBUGGING" , response.content)
            if response.content == "draft kosong":
                return "rewrite"
            else:
                return "generate"
            
    def generate_answer(self, state: AgentState):
        from app.services.llm_service import B2B_SYSTEM_PROMPT

        SYSTEM_PROMPT = (
            B2B_SYSTEM_PROMPT + """

Kamu menerima hasil query Neo4j Knowledge Graph.
Tugasmu: Buat laporan investigasi yang komprehensif berdasarkan data graf.

PANDUAN LAPORAN:
1. Sebutkan SEMUA entitas yang ditemukan (nama + konteks/jabatan).
2. Jelaskan SETIAP relasi dan maknanya dalam konteks investigasi.
3. Soroti potensi Conflict of Interest, Beneficial Ownership tersembunyi, atau Shell Company.
4. Jika ada alur keuangan (TRANSFERRED_TO), tampilkan sebagai timeline.
5. Jika data kosong/terbatas, jelaskan apa yang TIDAK ditemukan dan sarankan query alternatif.
6. Gunakan format terstruktur: bullet points, sub-judul, bold untuk nama entitas kunci.
7. Tutup dengan "Kesimpulan Investigasi" berisi temuan utama dan risk rating (Low/Medium/High).
"""
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("human", "Pertanyaan Investigasi: {question}\n\nData dari Knowledge Graph:\n{context}")
        ])

        chain  = prompt | self.llm
        response = chain.invoke({"question": state["question"], "context": state.get("graph_context", "[]")})
        logger.info("Final investigation answer generated")
        return {**state, "answer": response.content}
    
     ## HUMAN IN THE LOOP
     
    def route_rewrite_planning(self):
        keputusan = input("Apakah kamu ingin memberikan saran tambahan? (y/n)")
        
        if keputusan.lower() == "y":
            return "saran"
        elif keputusan.lower() == "n":
            return "end"
        
    def human_rewrite_planning(self, state: AgentState):
        
        saran = input("Apa yang perlu diperbaiki dan diperdalam?")
        PROMPT_REWRITE_PLANNING = f"""
            Kamu adalah seorang AI AGENT yang berfokus pada permintaan saran dari pengguna.
            kamu bekerja sama dengan planning agent, retriever agent, dan ecxtractor agent terhadap knowledge graph.
            kamu harus membuat saran dari pengguna menjadi mudah dimengerti oleh agent planning.
            
            berikut saran dari pengguna:
            {saran}
        """
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", PROMPT_REWRITE_PLANNING),
            ("human", "saran untuk agent planning : {saran}")
        ])
        
        chain = prompt | self.llm
        response = chain.invoke({"saran": saran})
        
        logger.info(f"✅ Berhasil menghasilkan saran dari user" )
        return {**state, "query_advice": response.content}

    # ── Graph Visualization ───────────────────────────────────────────────

    def get_graph_visualization(self, entity_filter: str = "") -> dict:
        """
        Query Neo4j and return nodes + edges in vis.js Network format.

        Args:
            entity_filter: optional entity name to centre the graph on.

        Returns:
            {"nodes": [...], "edges": [...]}
        """
        try:
            # ── Node query — generic, works with any labels ──────────────
            if entity_filter:
                node_query = """
                MATCH (n)
                WHERE any(prop IN keys(n) WHERE toString(n[prop]) CONTAINS $filter)
                WITH n
                OPTIONAL MATCH (n)-[*1..2]-(connected)
                WITH COLLECT(DISTINCT n) + COLLECT(DISTINCT connected) AS all_nodes
                UNWIND all_nodes AS node
                RETURN DISTINCT
                    coalesce(node.id, elementId(node))               AS id,
                    coalesce(node.name, node.id, elementId(node))    AS name,
                    labels(node)[0]                                  AS type,
                    coalesce(node.context, node.description, '')     AS context
                LIMIT 150
                """
                params = {"filter": entity_filter}
            else:
                node_query = """
                MATCH (n)
                RETURN
                    coalesce(n.id, elementId(n))                 AS id,
                    coalesce(n.name, n.id, elementId(n))         AS name,
                    labels(n)[0]                                 AS type,
                    coalesce(n.context, n.description, '')       AS context
                LIMIT 200
                """
                params = {}

            node_rows = self.graph.query(node_query, params)

            # ── Edge query — generic ─────────────────────────────────────
            edge_query = """
            MATCH (n)-[r]->(m)
            RETURN
                coalesce(n.id, elementId(n)) AS source,
                type(r)                      AS rel_type,
                coalesce(r.details, '')      AS details,
                coalesce(m.id, elementId(m)) AS target
            LIMIT 500
            """
            edge_rows = self.graph.query(edge_query)

            # ── Build vis.js data ────────────────────────────────────────
            GROUP_COLORS = {
                "Person":   "#3b82f6",
                "Company":  "#22c55e",
                "Address":  "#f59e0b",
                "Document": "#a855f7",
            }

            node_ids = {r["id"] for r in node_rows if r.get("id")}

            nodes = []
            for r in node_rows:
                nid = r.get("id")
                if not nid:
                    continue
                ntype = r.get("type", "Unknown")
                nodes.append({
                    "id":    nid,
                    "label": r.get("name", nid),
                    "group": ntype,
                    "title": f"<b>{r.get('name','')}</b><br>{ntype}<br><i>{r.get('context','')}</i>",
                    "color": GROUP_COLORS.get(ntype, "#94a3b8"),
                })

            edges = []
            seen_edges = set()
            for r in edge_rows:
                src, tgt, rtype = r.get("source"), r.get("target"), r.get("rel_type", "")
                if not (src and tgt and src in node_ids and tgt in node_ids):
                    continue
                key = (src, tgt, rtype)
                if key in seen_edges:
                    continue
                seen_edges.add(key)
                edges.append({
                    "from":  src,
                    "to":    tgt,
                    "label": rtype,
                    "title": r.get("details") or rtype,
                    "arrows": "to",
                })

            logger.info(f"📊 Graph viz: {len(nodes)} nodes, {len(edges)} edges")
            return {"nodes": nodes, "edges": edges}

        except Exception as exc:
            logger.error(f"❌ get_graph_visualization failed: {exc}")
            return {"nodes": [], "edges": []}


retriever_service = GraphRetrieverService()