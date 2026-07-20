# spikes/check_embeddings.py
from sentence_transformers import SentenceTransformer
model = SentenceTransformer("all-MiniLM-L6-v2")
vecs = model.encode(["Fed holds rates steady", "Interest rates unchanged"])
sim = float((vecs[0] @ vecs[1]) /
            ((vecs[0] @ vecs[0]) ** 0.5 * (vecs[1] @ vecs[1]) ** 0.5))
print(f"similarity: {sim:.3f}")