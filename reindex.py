"""
Script de réindexation : vide les chunks existants et régénère
tous les documents avec le nouveau découpage (chunking par phrases + overlap).
À lancer une seule fois après modification de decouper_en_chunks().
"""

from app import app
from models import db, Manuel, Chunk
from rag import indexer_document

with app.app_context():
    manuels = Manuel.query.all()

    if not manuels:
        print("Aucun manuel trouvé en base.")
    else:
        for manuel in manuels:
            print(f"\n=== Réindexation : {manuel.titre} (id={manuel.id_manuel}) ===")

            # 1. Supprime les anciens chunks de ce manuel
            nb_supprimes = Chunk.query.filter_by(id_manuel=manuel.id_manuel).delete()
            db.session.commit()
            print(f"🗑️  {nb_supprimes} anciens chunks supprimés")

            # 2. Réindexe avec le nouveau chunking
            if not manuel.chemin_fichier:
                print(f"⚠️  Pas de chemin_fichier pour ce manuel, on passe.")
                continue

            nb_chunks = indexer_document(manuel.chemin_fichier, manuel.id_manuel)
            print(f"✅ {nb_chunks} nouveaux chunks créés")

        print("\n=== Réindexation terminée ===")