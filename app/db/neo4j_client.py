import os
from neo4j import GraphDatabase
from app.core.logging import get_logger

logger = get_logger(__name__)

URI      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
USER     = os.getenv("NEO4J_USERNAME", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")


class Neo4jClient:
    def __init__(self):
        self.driver = None

    def connect(self):
        try:
            self.driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
            self.driver.verify_connectivity()
            logger.info(f"✅ Berhasil terhubung ke Neo4j: {URI} (db={DATABASE})")
        except Exception as e:
            logger.error(f"GAGAL KONEKSI KE NEO4J: {e}")

    def close(self):
        if self.driver:
            self.driver.close()
            logger.info("✅ Driver Neo4j ditutup.")

    def execute_query(self, query, parameters=None):
        if not self.driver:
            self.connect()
        logger.debug(f"Menjalankan Query: {query}")
        try:
            with self.driver.session(database=DATABASE) as session:
                result = session.run(query, parameters or {})
                records_list = [record.data() for record in result]
                logger.info(f"Query selesai. Ditemukan {len(records_list)} record.")
                return {"data": records_list, "query": query, "records_count": len(records_list)}
        except Exception as e:
            logger.error(f"Gagal execute Query: {e}")
            return None


if __name__ == "__main__":
    client = Neo4jClient()
    try:
        hasil = client.execute_query("MATCH (n) RETURN n LIMIT 5")
        print(hasil)
    except Exception as e:
        print("Error:", e)
    finally:
        client.close()
