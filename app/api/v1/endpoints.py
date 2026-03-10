from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
import os
from app.services.graph_extractor import GraphExtractorService
from app.services.workflow import build_retriever_graph

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

extractor = GraphExtractorService()

@app.route('/upload', methods=['POST'])
def upload_document():
    if 'file' not in request.files:
        return jsonify({"error": "Tidak ada bagian file"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Tidak ada file yang dipilih"}), 400
    
    if file:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        print(f"Mulai memproses file: {filename}...")
        
        # Memanggil method yang kamu rancang, mengirim filepath dan filename
        hasil_ekstraksi = extractor.process_uploaded_file_from_api(filepath, filename)
        
        if hasil_ekstraksi:
            # Print hasil di terminal server (sesuai keinginanmu)
            print("\n=== HASIL EKSTRAKSI ===")
            print(hasil_ekstraksi)
            
            # Kembalikan hasilnya ke pengguna dalam bentuk JSON
            return jsonify({
                "message": "Dokumen berhasil diproses dan disimpan ke Neo4j!",
                "filename": filename,
                "graf_result": hasil_ekstraksi
            }), 200
        else:
            return jsonify({"error": "Gagal mengekstrak teks atau dokumen kosong"}), 500

@app.route('/get-data', methods=['GET'])
def get_data():
        
    user_question = request.args.get("question")
    
    if not user_question:
        return jsonify({
            "status": "error",
            "message": "Parameter 'question' wajib diisi. Contoh: /get_data?question=siapa direktur PT X"
        }), 400
    
    try:
        graph = build_retriever_graph()
        inputs = {"question" : user_question}

        results = graph.invoke(inputs)
        final_answer = results.get("answer", "Maaf, tidak menemukan jawaban.")
        
        return jsonify({
            "status": "success",
            "input_question": user_question,
            "answer": final_answer,
            "cypher_used": results.get("cypher_query", ""),
            "raw_context": results.get("graph_context", "")
        }), 200
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Terjadi kesalahan pada server: {str(e)}"
        }), 500
    
    
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8000)
    
    