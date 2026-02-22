from langgraph.graph import StateGraph, END
from app.services.graph_retriever import AgentState, retriever_service

def build_retriever_graph():
    workflow = StateGraph(AgentState)

    # Tambahkan Node
    workflow.add_node("write_query", retriever_service.generate_cypher)
    workflow.add_node("run_query", retriever_service.execute_query)
    workflow.add_node("answer_user", retriever_service.generate_answer)
    workflow.add_node("planning", retriever_service.query_decomposition)

    # Hubungkan antar Node
    workflow.set_entry_point("planning")
    workflow.add_edge("planning", "write_query")
    workflow.add_edge("write_query", "run_query")
    # workflow.add_conditional_edges(
    #     "run_query",
    #     retriever_service.route_rewrite_query_cypher,
    #     {
    #         "generate": "answer_user",
    #         "rewrite" : "write_query"
    #     }
    # )
    workflow.add_edge("run_query", "answer_user")
    workflow.add_edge("answer_user", END)
    return workflow.compile()

# Contoh Penggunaan
if __name__ == "__main__":
    app = build_retriever_graph()
    inputs = {"question": "berikan aku semua relasi dari john doe"}
    
    for output in app.stream(inputs):
        for key, value in output.items():
            print(f"Node '{key}':")
            if value.get("answer"):
                print(f"Final Answer: {value['answer']}")