import os,httpx
class OpenAICompatibleEmbeddingService:
    local_only=False
    def __init__(self,base_url,model,api_key_env_name):self.base_url=base_url.rstrip("/");self.model=model;self.api_key_env_name=api_key_env_name
    def embed_texts(self,texts):
        key=os.getenv(self.api_key_env_name,"")
        if not key:raise RuntimeError(f"Embedding API key environment variable {self.api_key_env_name} is not configured")
        response=httpx.post(f"{self.base_url}/embeddings",json={"model":self.model,"input":texts},headers={"Authorization":f"Bearer {key}"},timeout=60);response.raise_for_status();return [item["embedding"] for item in response.json()["data"]]
    def embed_query(self,text):return self.embed_texts([text])[0]
class LocalEmbeddingService(OpenAICompatibleEmbeddingService):local_only=True
