import re
from typing import List, Optional, Literal
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from app.core.config import settings
from app.db.neo4j_client import Neo4jClient
from app.services.llm_service import GroqClient

from langchain_community.document_loaders import PyMuPDFLoader
import tempfile
import os

# ==========================================
# 1. DEFINISI SCHEMA (BLUEPRINT DATABASE)
# ==========================================

# Tipe Node yang relevan untuk detektif
class NodeType(str):
    PERSON = "Person"
    COMPANY = "Company"
    ADDRESS = "Address"
    DOCUMENT = "Document" # Bukti (SK, Akta, Berita)

# Tipe Relasi (Hubungan antar Node)
class RelationType(str):
    # Hubungan Kerja
    WORKS_AT = "WORKS_AT"           # Orang -> Perusahaan
    OWNS_SHARE = "OWNS_SHARE"       # Orang/Perusahaan -> Perusahaan (PENTING!)
    DIRECTOR_OF = "DIRECTOR_OF"     # Orang -> Perusahaan
    COMMISSIONER_OF = "COMMISSIONER_OF" # Komisaris
    
    # Hubungan Pribadi (Conflict of Interest)
    FAMILY_OF = "FAMILY_OF"         # Kakak/Adik/Anak
    MARRIED_TO = "MARRIED_TO"       # Suami/Istri
    
    # Lokasi & Bukti
    REGISTERED_AT = "REGISTERED_AT" # Perusahaan -> Alamat
    LIVES_AT = "LIVES_AT"           # Orang -> Alamat
    MENTIONED_IN = "MENTIONED_IN"   # Entitas -> Dokumen

# ==========================================
# 2. PYDANTIC MODELS (STRUCTURED OUTPUT)
# ==========================================

class Node(BaseModel):
    name: str = Field(..., description="Nama entitas. Contoh: 'Budi Santoso', 'PT. Maju Jaya'.")
    type: str = Field(..., description="Tipe entitas (Person, Company, Address, Document).")
    context: str = Field(..., description="Sangat Penting! Jabatan atau afiliasi unik untuk membedakan nama sama. Contoh: 'Direktur PT A', 'Supir Truk', 'Istri Pejabat X'.")
    
    @property
    def id(self) -> str:
        """
        Membuat ID unik otomatis: gabungan nama + konteks.
        Contoh: "Budi Santoso" + "Direktur" -> "budi_santoso_direktur"
        """
        clean_name = re.sub(r'[^a-zA-Z0-9]', '_', self.name.lower())
        clean_context = re.sub(r'[^a-zA-Z0-9]', '_', self.context.lower())
        return f"{clean_name}_{clean_context}"

class Relationship(BaseModel):
    source: Node = Field(..., description="Entitas asal")
    target: Node = Field(..., description="Entitas tujuan")
    type: str = Field(..., description="Jenis hubungan (Gunakan HURUF KAPITAL SNAKE_CASE, misal: WORKS_AT).")
    details: Optional[str] = Field(None, description="Keterangan tambahan. Misal: 'Saham 50%' atau 'Adik kandung'.")

class ExtractionResult(BaseModel):
    nodes: List[Node]
    relationships: List[Relationship]

# ==========================================
# 3. SERVICE CLASS UTAMA
# ==========================================


class GraphExtractorService:
    def __init__(self):
        # Inisialisasi Llama-3 via Groq
        groq_client = GroqClient()
        self.llm = groq_client.get_llm().with_structured_output(ExtractionResult)


    def extract(self, text: str, source_doc: str = "Unknown Source") -> ExtractionResult:
        """
        Fungsi utama: Terima Teks -> Keluar Objek Graph
        """
        print(f"🕵️  AI Detective sedang membaca data...")
        
        system_prompt = """
        Kamu adalah AI Investigator Forensik Elit. Tugasmu adalah membaca dokumen investigasi dan mengekstrak Knowledge Graph.
        
        ATURAN UTAMA:
        1.  **Entity Resolution**: Jika menemukan nama orang, WAJIB sertakan konteks (jabatan/afiliasi) di field 'context'. 
            Jangan biarkan context kosong!
            - SALAH: name="Agus", context=""
            - BENAR: name="Agus", context="Direktur PT X"
            
        2.  **Conflict of Interest**: Fokus mencari hubungan keluarga (istri, anak, kakak) dan kepemilikan saham tersembunyi.
        
        3.  **Addresses**: Jika ada alamat yang sama antara Pejabat dan Vendor, ekstrak dengan teliti sebagai node 'Address'.
        
        ATURAN KHUSUS (ADVANCED):
        1.  **Digital Footprint**: Jika menemukan kesamaan Email, No HP, atau Alamat antara dua entitas berbeda, EKSTRAK ITU SEBAGAI HUBUNGAN!
            -   Contoh: (Person)-[:USES_EMAIL]->(EmailAddress)<-[:USES_EMAIL]-(Company)
            -   Ini menandakan kepemilikan tersembunyi (Beneficial Ownership).
            
        2.  **Financial Flow**: Cari nominal uang dan tanggal transaksi. Masukkan ke dalam 'details' relasi.
            -   Tipe Relasi: TRANSFERRED_TO

        3.  **Shell Companies**: Perhatikan perusahaan di negara Tax Haven (BVI, Panama, Cayman). Tandai konteksnya sebagai 'Shell Company'.

        """

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", f"Dokumen Sumber: {source_doc}\n\nIsi Teks:\n{text}")
        ])

        chain = prompt | self.llm
        result = chain.invoke({})
        return result

    def load_pdf_content(self, file_path: str) -> str:
        """Menggunakan LangChain PyMuPDFLoader untuk membaca PDF"""
        loader = PyMuPDFLoader(file_path)
        documents = loader.load()

        full_text = "\n".join([doc.page_content for doc in documents])
        return full_text
    
    def process_uploaded_file(self, uploaded_file):
        """Handle file upload dari Streamlit menggunakan temporary file"""
        # Buat file sementara karena PyMuPDFLoader butuh path string
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(uploaded_file.read())
            tmp_path = tmp_file.name

        try:
            if uploaded_file.type == "application/pdf":
                text = self.load_pdf_content(tmp_path)
            else:
                # Untuk TXT tetap bisa baca langsung
                text = uploaded_file.getvalue().decode("utf-8")

            if text.strip():
                # Jalankan ekstraksi LLM
                extraction_result = self.extract(text, source_doc=uploaded_file.name)
                # Simpan ke Neo4j
                self.save_to_neo4j(extraction_result)
                return True
        finally:
            # Hapus file sementara setelah selesai
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        
        return False
    
    def save_to_neo4j(self, data: ExtractionResult):
        """
        Menyimpan hasil ekstraksi ke Database Neo4j dengan query Cypher yang aman.
        """
        if not data.nodes and not data.relationships:
            print("⚠️  Tidak ada data yang diekstrak.")
            return

        print(f"💾 Menyimpan {len(data.nodes)} Nodes dan {len(data.relationships)} Relasi ke Neo4j...")

        # Query untuk Node (Pakai MERGE biar gak duplikat)
        node_query = """
        UNWIND $nodes AS n
        MERGE (node:Entity {id: n.id})
        SET node.name = n.name,
            node.context = n.context,
            node.type = n.type
        WITH node, n
        CALL apoc.create.addLabels(node, [n.type]) YIELD node AS labeledNode
        RETURN count(labeledNode)
        """
        
        # Siapkan data nodes untuk dikirim
        nodes_dict = [{"id": n.id, "name": n.name, "context": n.context, "type": n.type} for n in data.nodes]
        
        try:
            # 1. Simpan Nodes Dulu
            neo4j_client = Neo4jClient()
            neo4j_client.execute_query(node_query, {"nodes": nodes_dict})
            
            # 2. Simpan Relasi
            rel_query = """
            UNWIND $rels AS r
            MATCH (source:Entity {id: r.source_id})
            MATCH (target:Entity {id: r.target_id})
            CALL apoc.create.relationship(source, r.type, {details: r.details}, target) YIELD rel
            RETURN count(rel)
            """
            
            rels_dict = [{
                "source_id": r.source.id,
                "target_id": r.target.id,
                "type": r.type.upper().replace(" ", "_"),
                "details": r.details or ""
            } for r in data.relationships]
            
            neo4j_client.execute_query(rel_query, {"rels": rels_dict})
            print("✅ SUKSES! Data Investigasi tersimpan di Graph.")
            
        except Exception as e:
            print(f"❌ Error Neo4j: {e}")
            print("Tips: Pastikan plugin APOC sudah diinstall di Neo4j Desktop!")

# Instance singleton biar bisa dipanggil di mana-mana
extractor_service = GraphExtractorService()