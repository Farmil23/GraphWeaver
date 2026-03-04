import streamlit as st
from app.services.workflow import build_retriever_graph
from app.services.graph_extractor import GraphExtractorService
# Konfigurasi Halaman
st.set_page_config(page_title="GraphWeaver Investigator", page_icon="🕵️‍♂️")


from app.services.graph_extractor import extractor_service

with st.sidebar:
    st.title("📁 Data Management")
    uploaded_file = st.file_uploader("Upload Dokumen Investigasi (PDF/TXT)", type=["pdf", "txt"])
    
    if uploaded_file is not None:

        if f"processed_{uploaded_file.name}" not in st.session_state:
            with st.spinner(f"Sedang mengekstrak entitas dari {uploaded_file.name}..."):
                success = extractor_service.process_uploaded_file(uploaded_file)
                if success:
                    st.session_state[f"processed_{uploaded_file.name}"] = True
                    st.success(f"✅ {uploaded_file.name} berhasil masuk ke Graph!")
                else:
                    st.error("Gagal mengekstrak teks dari dokumen.")
        else:
            st.info(f"ℹ️ {uploaded_file.name} sudah diproses.")
            
            
st.title("GraphWeaver")
st.markdown("### AI-Powered Forensic Investigator Agent")
st.info("Uncovering hidden connections in Knowledge Graphs")

def get_agent():
    return build_retriever_graph()


investigator_agent = get_agent()

if "messages" not in st.session_state:
    st.session_state.messages = []
    
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        
# if prompt := st.chat_input("Tanyakan entitas atau relasi dari graph..."):
#     st.session_state.messages.append({"role" : "user", "content": prompt})
#     with st.chat_message("user"):
#         st.markdown(prompt)
        
#     with st.chat_message("assistant"):
#         with st.spinner("Investagiting Graph..."):
#             try:
#                 inputs = {"question" : prompt}
#                 results =investigator_agent.invoke(inputs)
                
                
                
#                 final_answer = results.get("answer", "maaf, saya tidak menemukan jawabannya")
                
#                 st.markdown(final_answer)
#                 st.session_state.messages.append({"role": "assistant", "content": final_answer})
#             except Exception as e:
#                 st.error(f"Error: {str(e)}")
    
    
if prompt := st.chat_input("Tanyakan entitas atau relasi dari graph..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
        
    with st.chat_message("assistant"):
        # Placeholder untuk menampilkan langkah-langkah agen
        status_placeholder = st.empty()
        # Placeholder untuk jawaban akhir
        answer_placeholder = st.empty()
        
        try:
            inputs = {"question": prompt}
            
            # Menggunakan .stream() untuk mendapatkan output setiap node
            for output in investigator_agent.stream(inputs):
                for node_name, node_output in output.items():
                    # Menampilkan nama node yang sedang berjalan di status
                    status_placeholder.status(f"🛠️ Agent Node: {node_name} sedang bekerja...").update(state="running")
                    
                    # Opsional: Tampilkan detail teknis di expander (bagus untuk demo)
                    with st.expander(f"Log: {node_name}"):
                        if node_name == "planning":
                            st.write(node_output["query_decomposition"])
                        elif node_name == "write_query":
                            st.write(node_output["cypher_query"])
                        elif node_name == "run_query":
                            st.write(node_output["graph_context"])
                        elif node_name == "answer_user":
                            st.write(node_output["answer"])
                            
                    if "answer" in node_output:
                        final_answer = node_output["answer"]
                        answer_placeholder.markdown(final_answer)
                        st.session_state.messages.append({"role": "assistant", "content": final_answer})
            
            status_placeholder.status("✅ Investigasi Selesai").update(state="complete")

        except Exception as e:
            st.error(f"Error: {str(e)}") 