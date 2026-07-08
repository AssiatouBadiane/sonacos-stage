from app import app
from models import db, Manuel, Chunk
from rag import indexer_document

with app.app_context():
    manuels = Manuel.query.all()
    for m in manuels:
        print(f"Ré-indexation : {m.titre}")
        Chunk.query.filter_by(id_manuel=m.id_manuel).delete()
        db.session.commit()
        indexer_document(m.chemin_fichier, m.id_manuel)
    print("✅ Ré-indexation terminée.")