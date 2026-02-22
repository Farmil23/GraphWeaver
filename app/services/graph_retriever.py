from typing import TypedDict, List, Optional
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_neo4j import Neo4jGraph
from app.core.config import settings
from app.services.graph_extractor import NodeType, RelationType
from app.services.llm_service import GroqClient
from app.services.graph_extractor import ExtractionResult, GraphExtractorService
from app.db.neo4j_client import Neo4jClient
from app.core.logging import get_logger

from app.core.logging import setup_logging
setup_logging() # Wajib dipanggil di awal
logger = get_logger(__name__)

# 1. Definisi State agar data mengalir dengan konsisten
class AgentState(TypedDict):
    question: str
    cypher_query: Optional[str]
    graph_context: Optional[str]
    answer: Optional[str]
    query_decomposition : str

class GraphRetrieverService:
    def __init__(self):
        # Koneksi ke Neo4j via LangChain
        self.graph = Neo4jGraph(
            url=settings.NEO4J_URI,
            username=settings.NEO4J_USER,
            password=settings.NEO4J_PASSWORD
        )
        
        # LLM untuk generate Cypher
        groq_client = GroqClient()
        self.llm = groq_client.get_llm()

    def _get_system_prompt(self):
        # Mengambil daftar tipe dari extractor agar sinkron
        labels = ['Person', 'Company', 'Address', 'Document']
        rel_types = [ 'RESIDES_AT', 'SPOUSE', "PERSONAL_SECRETARY_FOR", "LOCATED_AT", "USES_EMAIL", 'DIRECTOR_OF', 'REGISTERED_AT', 'TRANSFERRED_TO']
        
        examples = [
            {"question" : "siapa pemilik perusahaan blue ocean holdings Ltd?", 
             "cyper" :  """MATCH (c:Company) WHERE c.name       CONTAINS "Blue Ocean Holdings Ltd"
                        MATCH (owner:Person)-[:DIRECTOR_OF]->(c)
                        OPTIONAL MATCH (owner)-[rel]-(connected)
                        RETURN owner, rel, connected"""},
            {"question" : " siapa joko widodo dan apa keterhubungannnya dengan sri wahyuni?", 
             "cyper" :  """MATCH (p1:Person) WHERE p1.name CONTAINS "Joko Widodo"
                        MATCH (p2:Person) WHERE p2.name CONTAINS "Sri Wahyuni"
                        MATCH path = (p1)-[:SPOUSE|PERSONAL_SECRETARY_FOR|DIRECTOR_OF|USES_EMAIL|RESIDES_AT|LOCATED_AT|REGISTERED_AT|TRANSFERRED_TO*]-(p2)
                        RETURN path"""},
            {"question" : "tempat tinggal joko widodo itu sama dengan tempat perusahaan apa?", 
             "cyper" :  """ MATCH (p:Person) WHERE p.name CONTAINS "Joko Widodo"
                        MATCH (p)-[:RESIDES_AT]-(a:Address)
                        MATCH (c:Company)-[:LOCATED_AT]-(a)
                        RETURN a, c"""},
            {"question" : "berikan aku semua relasi dari john doe", 
             "cyper" :  """ MATCH (p:Person) WHERE p.name CONTAINS "John Doe"
                        MATCH (p)-[r:RESIDES_AT|SPOUSE|PERSONAL_SECRETARY_FOR|LOCATED_AT|USES_EMAIL|DIRECTOR_OF|REGISTERED_AT|TRANSFERRED_TO]-(connected)
                        OPTIONAL MATCH (connected)-[r2:RESIDES_AT|SPOUSE|PERSONAL_SECRETARY_FOR|LOCATED_AT|USES_EMAIL|DIRECTOR_OF|REGISTERED_AT|TRANSFERRED_TO]-(other)
                        RETURN p, r, connected, r2, other"""},
            {"question" : "berikan aku semua relasi dari john doe", 
             "cyper" :  """ MATCH (p:Person)
                        WHERE p.name CONTAINS 'John Doe'
                        OPTIONAL MATCH (p)-[r1:RESIDES_AT|SPOUSE|PERSONAL_SECRETARY_FOR|LOCATED_AT|USES_EMAIL|DIRECTOR_OF|REGISTERED_AT|TRANSFERRED_TO]->(n1)
                        OPTIONAL MATCH (p)<-[r2:RESIDES_AT|SPOUSE|PERSONAL_SECRETARY_FOR|LOCATED_AT|USES_EMAIL|DIRECTOR_OF|REGISTERED_AT|TRANSFERRED_TO]-(n2)
                        OPTIONAL MATCH (n1)-[r3:RESIDES_AT|SPOUSE|PERSONAL_SECRETARY_FOR|LOCATED_AT|USES_EMAIL|DIRECTOR_OF|REGISTERED_AT|TRANSFERRED_TO]->(m1)
                        OPTIONAL MATCH (n1)<-[r4:RESIDES_AT|SPOUSE|PERSONAL_SECRETARY_FOR|LOCATED_AT|USES_EMAIL|DIRECTOR_OF|REGISTERED_AT|TRANSFERRED_TO]-(m2)
                        OPTIONAL MATCH (n2)-[r5:RESIDES_AT|SPOUSE|PERSONAL_SECRETARY_FOR|LOCATED_AT|USES_EMAIL|DIRECTOR_OF|REGISTERED_AT|TRANSFERRED_TO]->(m3)
                        OPTIONAL MATCH (n2)<-[r6:RESIDES_AT|SPOUSE|PERSONAL_SECRETARY_FOR|LOCATED_AT|USES_EMAIL|DIRECTOR_OF|REGISTERED_AT|TRANSFERRED_TO]-(m4)
                        RETURN p, r1, r2, n1, n2,
                            r3, r4, m1, m2,
                            r5, r6, m3, m4"""},
        ]
        
        return f"""
        Kamu adalah AI Investigator Forensik Elit dan pakar Neo4j Cypher.
        Tugasmu: Mengubah pertanyaan user menjadi query Cypher untuk mencari bukti.
    
        SKEMA GRAF:
        - Node Labels: {labels}
        - Relationship Types: {rel_types}
        - Properti Utama: id, name, type, context
        - PANDUAN : {examples}

        ATURAN OUTPUT (WAJIB):
        1. Kembalikan HANYA query Cypher murni. 
        2. JANGAN sertakan teks penjelasan, markdown, atau komentar apapun.
        3. FORMAT ID: Selalu gunakan format 'nama_konteks' (lowercase, underscore).
           Contoh: MATCH (e:Entity {{id: "bapak_hartono_sekretaris_pribadi", context: "Direktur..."}})
        4. Jika tidak yakin dengan ID lengkap, gunakan pencarian property 'name' dengan CONTAINS.
        5. FORMAT PROPERTY NAME: Gunakan kapital misal john doe menjadi John Doe.
            CONTOH  MATCH (e:Person {{name: "John Doe", context: "Direktur..."}}) 
        """
        
    def _get_query_decomposition(self):
        # Mengambil daftar tipe dari extractor agar sinkron
        labels = ['Person', 'Company', 'Address', 'Document']
        rel_types = [ 'RESIDES_AT', 'SPOUSE', "PERSONAL_SECRETARY_FOR", "LOCATED_AT", "USES_EMAIL", 'DIRECTOR_OF', 'REGISTERED_AT', 'TRANSFERRED_TO']
        
        return f"""
        Kamu adalah AI Investigator Forensik Elit dan pakar Neo4j Cypher.
        Tugasmu: Mengubah pertanyaan user menjadi ringkasan relationship yang nantinya akan diubahn menjadi query cyper oleh Agent writer_cypher.
        JIKA ADA PERTANYAAN MISALKAN Apartemen SCBD Tower 2 unit 501 DI JAKARTA ubah menjadi seperti ini "Apartemen SCBD Tower 2, Unit 505, Jakarta" LANGSUNG DIGABUNG SAJA JANGAN MENGGUNAKAN WHERE 

        SKEMA GRAF:
        - Node Labels: {labels}
        - Relationship Types: {rel_types}
        - Properti Utama: id, name, type, context

        ATURAN OUTPUT (WAJIB):
        1. BERIKAN OUTPUT YANG JELAS AGAR AGENT WRITER CYPHER MENGERTI 
            CONTOH:
                beritahu aku hubungan antara perusahan yang direrutnya adalah john doe.
                OUTPUT:
                    john doe directur dari perusahan apa? cari hubungan dengan DIRECTOR_OF
                    lalu cari hubungan untuk perusahaan tersebut dengan semua relasi yang dimilikinya.
        2. Jika tidak yakin dengan ID lengkap, gunakan pencarian property 'name' dengan CONTAINS.
        3. IKUTI SCHEMA YANG DIBERIKAN JANGAN BERIKAN NODE YANG TIDAK ADA DI SKEMA GRAF (jangan berikan city hanya berikan yang ada di dalam schema).
        4. SETIAP PROPERTI name harus menggunakan Capital Case di awal Hurufnya misalkan john doe menjadi John Doe.
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
        
        system_content = self._get_query_decomposition()
        
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
        """
        Node untuk mengeksekusi query Cypher yang sudah di-generate LLM.
        """
        try:
            # Menggunakan query dari state untuk mencari data di Neo4j
            query = state["cypher_query"]
            
            # Pastikan query tidak kosong
            if not query or "Error" in query:
                return {**state, "graph_context": "Tidak ada query yang valid untuk dijalankan."}

            # Menjalankan query READ
            results = self.graph.query(query)
            
            logger.info(f"berhasil menjalankan Query : {results}")
            
            # Simpan hasil dalam bentuk string untuk diproses node 'generate_answer'
            return {**state, "graph_context": str(results)}
            
        except Exception as e:
            logger.error(f"❌ Error saat menjalankan query: {e}")
            return {**state, "graph_context": f"Gagal mengambil data dari database: {str(e)}"}

    def route_rewrite_query_cypher(self, state: AgentState):

            graph_context = state.get("graph_context", "")
            SYSTEM_PROMPT = """
                kamu adalah seorang AI Detektif yang bekerja sama dengan hasil Node dan context dari data Graph.
                kamu nantinya akan mendapatkan context utama dari graph dan kamu diwajibkan menjawab pertanyaan secara formal dan juga memiliki makna tersendiri.
                JIKA MISALKAN CONTEXT YANG DIDAPAT BERNILAI KOSONG KELUARKAN = "draft kosong" NAMUN JIKA MISALKAN CONTEXT GRAPH UDAH SESUAI MAKA KELUARKAN = "answer_user"
            """
            
            prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("human", "Pertanyaan: {question}\nData Graf: {context}")
            ])
            
            chain = prompt | self.llm
            response = chain.invoke({"question": state["question"], "context": graph_context})
            
            if response.content == "draft kosong":
                return "generate"
            else:
                return "rewrite"
            
    def generate_answer(self, state: AgentState):
        
        SYSTEM_PROMPT = """
            kamu adalah seorang AI Detektif yang bekerja sama dengan hasil Node dan context dari data Graph.
            kamu nantinya akan mendapatkan context utama dari graph dan kamu diwajibkan menjawab pertanyaan secara formal dan juga memiliki makna tersendiri.
            namun kamu harus menjawab sesuai dengan data graf yang diberikan.
            aku ingin kamu memberikan output sesuai dengann context dan lengkap, misal di graph ada beberapa property, berikan semuanya sebagai context tambahan.
            
        
        """
        prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("human", "Pertanyaan: {question}\nData Graf: {context}")
        ])
        
        chain = prompt | self.llm
        response = chain.invoke({"question": state["question"], "context": state["graph_context"]})
        logger.info(f"✅ Berhasil menghasilkan final answer" )
        return {**state, "answer": response.content}

retriever_service = GraphRetrieverService()