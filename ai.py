import os
from groq import Groq
from rag import rechercher_chunks

_client = None


def get_client():
    global _client
    if _client is None:
        _client = Groq(api_key=os.environ.get('GROQ_API_KEY'))
    return _client


def generer_reponse(question, id_manuel=None):
    """
    Pipeline RAG :
    1. Cherche les chunks pertinents
    2. Construit le prompt
    3. Envoie à Llama 3 via Groq
    4. Retourne la réponse + les sources
    """
    salutations = ['bonjour', 'bonsoir', 'salut', 'hello', 'hi', 'coucou', 'bonne journée']
    if any(mot in question.lower() for mot in salutations):
        return {
            'reponse': "Bonjour ! Je suis votre assistant IA de la SONACOS. Je suis là pour répondre à vos questions sur les procédures officielles de l'entreprise. En quoi puis-je vous aider ?",
            'sources': []
        }

    chunks = rechercher_chunks(question, id_manuel=id_manuel, top_k=3)

    if not chunks:
        return {
            'reponse': "Je n'ai pas trouvé d'information pertinente dans les documents disponibles.",
            'sources': []
        }

    contexte = "\n\n".join([
        f"[Page {chunk.num_page}]\n{chunk.extrait_texte}"
        for chunk in chunks
    ])

    prompt = f"""Tu es un assistant intelligent de la SONACOS.
Tu dois répondre aux questions des employés en te basant UNIQUEMENT sur les documents officiels fournis.
Si la réponse n'est pas dans les documents, dis-le clairement.

DOCUMENTS OFFICIELS :
{contexte}

QUESTION : {question}

RÉPONSE :"""

    client = get_client()
    completion = client.chat.completions.create(
        model=os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile'),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=1000
    )

    reponse = completion.choices[0].message.content

    sources = [
        {'page': chunk.num_page, 'extrait': chunk.extrait_texte[:150] + '...'}
        for chunk in chunks
    ]

    phrases_sans_source = [
        "je n'ai pas", "je ne trouve pas", "aucune information",
        "pas d'information", "pas trouvé", "ne mentionne pas",
        "ne contient pas", "ne figure pas", "n'est pas mentionné",
        "n'apparaît pas", "ne précise pas", "pas de réponse",
        "cannot find", "not found"
    ]
    afficher_sources = not any(phrase in reponse.lower() for phrase in phrases_sans_source)

    return {
        'reponse': reponse,
        'sources': sources if afficher_sources else []
    }
