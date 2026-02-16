<div align="center">

# 🕵️‍♂️ GraphWeaver
### AI-Powered Forensic Investigator Agent

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Neo4j](https://img.shields.io/badge/Neo4j-008CC1?style=for-the-badge&logo=neo4j&logoColor=white)](https://neo4j.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agentic_Workflow-FF6C37?style=for-the-badge&logo=langchain&logoColor=white)](https://langchain.com)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Llama 3](https://img.shields.io/badge/Model-Llama_3_70B-0467DF?style=for-the-badge&logo=meta&logoColor=white)](https://groq.com)

<p align="center">
  <b>Uncovering hidden connections that traditional search engines miss.</b><br>
  Transforming unstructured documents into actionable Knowledge Graphs for Anti-Fraud & Due Diligence.
</p>

[View Demo](#-demo-the-blue-ocean-scandal) • [Read Docs](#-documentation) • [Report Bug](https://github.com/Farmil23/graph-weaver/issues)

</div>

---

## 📖 Overview

**GraphWeaver** is an autonomous AI agent designed for **Corporate Due Diligence** and **Anti-Fraud Investigation**. Traditional keyword searches often fail to spot complex schemes like money laundering loops or hidden beneficial ownerships.

By combining **Large Language Models (LLM)** with **GraphRAG (Retrieval Augmented Generation)**, GraphWeaver ingests unstructured text (legal docs, news, reports), structures them into a network of entities, and autonomously queries the graph to reveal:

* 🚩 **Conflicts of Interest** (e.g., Officials awarding contracts to family members).
* 💸 **Money Laundering Circles** (e.g., Circular fund transfers).
* 🏢 **Shell Company Networks** (e.g., Entities registered in tax havens with shared addresses).

---

## 🏗️ System Architecture

GraphWeaver operates on a microservices architecture orchestrated by **LangGraph**.

```mermaid
graph TD
    User([User / Client]) -->|HTTP POST /investigate| API[FastAPI Gateway]
    
    subgraph "🕵️ Agentic Workflow (LangGraph)"
        API -->|Dispatch| Supervisor{Supervisor Node}
        Supervisor -->|Task: Parse| Extractor[Llama-3 Extraction Agent]
        Supervisor -->|Task: Query| QueryGen[Cypher Query Generator]
        Supervisor -->|Task: Reason| Analyst[Insight Reasoning Agent]
    end
    
    subgraph "🧠 Knowledge Engine"
        Extractor -->|Write Nodes/Edges| Neo4j[(Neo4j Graph DB)]
        QueryGen -->|Read Context| Neo4j
        Neo4j <-->|Hybrid Search| Vector[Vector Index]
    end

    Analyst -->|Final Report| API


```
