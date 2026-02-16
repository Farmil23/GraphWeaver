## LLM LIBRARY
from langchain_groq import ChatGroq

# SYSTEM SETUP
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

class GroqClient:
    def __init__(self):
        self.llm = None
    
    def get_llm(self, model_name = "openai/gpt-oss-120b"):
        try:
            self.llm = ChatGroq(model= model_name, api_key = settings.GROQ_API_KEY, temperature=0.0,)
            logger.info(f"✅ Berhasil terhubung dengan model LLM")
            
            return self.llm
        
        except Exception as e:
            logger.error(f"[ERROR] GAGAL KONEKSI KE GROQ: ", e)
            
    def execute_model(self, query):
        try:
            llm = self.get_llm()
            
            result = llm.invoke(query)
            
            logger.info("Berhasil Eksekusi Query")
            return {
                "result" : result,
                "model" : llm.model_name,
                "verbose" : llm.verbose
            }
            
        except Exception as e:
            logger.error("ERROR - Gagal execute Query: ", e)
            return None
        
if __name__ == "__main__":
    from app.core.logging import setup_logging
    
    setup_logging()
    groq_client = GroqClient()
    
    try:
        response = groq_client.execute_model("hayy")
        result = response["result"].content
        model = response["model"]
        verbose = response["verbose"]
        
        print(f"Hasil Jawaban: {result} \n dari model {model} \n dengan verbose {verbose}")
        
    except Exception as e:
        print(e)
        