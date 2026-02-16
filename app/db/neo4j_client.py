from neo4j import GraphDatabase
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

class Neo4jClient:
    def __init__(self):
        self.driver = None

    def connect(self):
        try:
            self.driver = GraphDatabase.driver(
                settings.NEO4J_URI, 
                auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
            )
            logger.info(f"✅ Berhasil terhubung ke Neo4j di {settings.NEO4J_URI}")
        except Exception as e:
            logger.error(f"[ERROR] GAGAL KONEKSI KE NEO4J: ", e)
            
    def close(self):
        if self.driver:
            self.driver.close()
            logger.info(f"✅ Driver Berhasil ditutup!.")

    def execute_query(self, query, parameters=None):
        if not self.driver:
            self.connect()
        
        logger.debug(f"Menjalankan Query: {query}")
        
        try:
            with self.driver.session() as session:
                result = session.run(query, parameters)

                records_list = [record.data() for record in result]
                
                response = {
                    "data": records_list,
                    "query": query,
                    "records_count": len(records_list)
                }
                
                logger.info(f"Query selesai. Ditemukan {len(records_list)} data.")
                return response
        except Exception as e:
            logger.info("ERROR - Gagal execute Query: ", e)
            return None
            
if __name__ == "__main__":
    from app.core.logging import setup_logging
    
    setup_logging()
    
    neo4j_client = Neo4jClient()
    try:
        hasil = neo4j_client.execute_query("MATCH (n:Project) RETURN n LIMIT 25;", None)
        data, query, records = hasil["data"], hasil["query"], hasil["records_count"]
        print(f"Ditemukan {data} \n dengan query {query} \n dengan total record {records}")
    except Exception as e:
        print("Ada masalah pada", e)
    finally:
        neo4j_client.close()