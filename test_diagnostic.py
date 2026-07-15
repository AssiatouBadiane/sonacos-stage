from app import app
from rag import get_model, get_embeddings_manuel, scores_mot_cle_par_chunk
from sklearn.metrics.pairwise import cosine_similarity

with app.app_context():
    question = "procedure de conge"
    model = get_model()
    q_emb = model.encode(question)

    data = get_embeddings_manuel(3)
    chunks, matrix = data['chunks'], data['matrix']
    similarites = cosine_similarity([q_emb], matrix)[0]
    boosts = scores_mot_cle_par_chunk(question, 3)

    resultats = []
    for chunk, sim in zip(chunks, similarites):
        boost = boosts.get(chunk.id_chunk, 0.0)
        resultats.append((chunk, sim, boost, sim + 6.0 * boost))

    resultats.sort(key=lambda x: x[3], reverse=True)
    for chunk, sim, boost, total in resultats[:8]:
        print(f"Page {chunk.num_page} | sem={sim:.3f} boost={boost:.3f} total={total:.3f} | {chunk.extrait_texte[:80]}...")
        
print("\n--- Contenu complet page 138 ---")
for c in chunks:
    if c.num_page == 138:
        print(c.extrait_texte)
        print("---")      
        
print("\n--- Contenu complet page 128 ---")
for c in chunks:
    if c.num_page == 128:
        print(c.extrait_texte)
        print("---")          