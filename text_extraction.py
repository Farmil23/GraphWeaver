import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.services.graph_extractor import extractor_service

# Kasus Pencucian Uang yang Rumit
kasus_complex = """
        Penyelidikan lebih lanjut terhadap struktur kepemilikan mengungkap bahwa Bapak Hartono merupakan suami dari Ibu Linda Wijaya. Berdasarkan database registrasi perusahaan, Ibu Linda Wijaya menjabat sebagai Direktur di CV. Cahaya Makmur, sebuah vendor utama bagi PT. Sumber Rejeki Abadi.

        Secara mengejutkan, CV. Cahaya Makmur tercatat memiliki alamat kantor di Jl. Jenderal Sudirman No. 88, yang setelah diverifikasi merupakan lokasi yang sama dengan kantor pusat PT. Sumber Rejeki Abadi.

        Selain itu, ditemukan sebuah dokumen audit berkode 'DOC-2024-X' yang menunjukkan adanya instruksi transfer dari CV. Cahaya Makmur ke rekening pribadi Mr. John Doe sebulan sebelum Blue Ocean Holdings didirikan.

        Terakhir, jejak digital menunjukkan bahwa Mr. John Doe sebelumnya pernah bekerja sebagai Sekretaris Pribadi bagi Ibu Linda Wijaya selama lima tahun, sebelum akhirnya dia pindah ke British Virgin Islands untuk mengelola entitas asing tersebut.
        """

def main():
    print("🕵️ Memulai Investigasi Skandal Blue Ocean...")
    
    # 1. Ekstrak
    hasil = extractor_service.extract(kasus_complex, source_doc="Pandora Leak #99")
    
    # 2. Print Hasil biar kelihatan logic-nya
    print("\n--- 🔍 TEMUAN ENTITAS ---")
    for n in hasil.nodes:
        print(f"• {n.name} ({n.type}) -> {n.context}")

    print("\n--- 🔗 TEMUAN HUBUNGAN ---")
    for r in hasil.relationships:
        print(f"• {r.source.name} --[{r.type}]--> {r.target.name}")
        if r.details:
            print(f"  └─ Detail: {r.details}")

    # 3. Simpan
    extractor_service.save_to_neo4j(hasil)
    print("\n✅ Data tersimpan. Silakan cek Neo4j Browser!")

if __name__ == "__main__":
    main()