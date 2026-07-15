from app import app
from rag import rechercher_chunks

with app.app_context():
    for question in ["solde de conge", "procedure de conge"]:
        print(f"\n=== {question} ===")
        chunks = rechercher_chunks(question, id_manuel=3, top_k=5)
        for c in chunks:
            print(f"Page {c.num_page} : {c.extrait_texte[:100]}...")