from raceintel.retrieval.chroma_client import ChromaClient

client = ChromaClient()

client.reset_collection()

print("Knowledge base reset.")