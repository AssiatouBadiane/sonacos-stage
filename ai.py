import os
from groq import Groq
from rag import rechercher_chunks

_client = None


def get_client():
    global _client
    if _client is None:
        _client = Groq(api_key=os.environ.get('GROQ_API_KEY'))
    return _client


def generer_reponse(question, id_manuel=None, langue='fr'):
    """
    Pipeline RAG :
    1. Cherche les chunks pertinents
    2. Construit le prompt (dans la langue choisie)
    3. Envoie à Llama 3 via Groq
    4. Retourne la réponse + les sources
    """
    salutations_fr = ['bonjour', 'bonsoir', 'salut', 'coucou', 'bonne journée']
    salutations_en = ['hello', 'hi', 'good morning', 'good evening']

    if langue == 'en':
        if any(mot in question.lower() for mot in salutations_en + salutations_fr):
            return {
                'reponse': "Hello! I'm the SONACOS AI assistant. I'm here to answer your questions about the company's official procedures. How can I help you?",
                'sources': []
            }
    else:
        if any(mot in question.lower() for mot in salutations_fr + salutations_en):
            return {
                'reponse': "Bonjour ! Je suis votre assistant IA de la SONACOS. Je suis là pour répondre à vos questions sur les procédures officielles de l'entreprise. En quoi puis-je vous aider ?",
                'sources': []
            }

    chunks = rechercher_chunks(question, id_manuel=id_manuel, top_k=3)

    if not chunks:
        msg = "I couldn't find any relevant information in the available documents." if langue == 'en' else "Je n'ai pas trouvé d'information pertinente dans les documents disponibles."
        return {'reponse': msg, 'sources': []}

    contexte = "\n\n".join([
        f"[Page {chunk.num_page}]\n{chunk.extrait_texte}"
        for chunk in chunks
    ])

    if langue == 'en':
        prompt = f"""You are an intelligent assistant for SONACOS.
You must answer employee questions using ONLY the official documents provided below.
If the answer is not in the documents, say so clearly.
Always respond in English, regardless of the language of the source documents.

OFFICIAL DOCUMENTS:
{contexte}

QUESTION: {question}

ANSWER:"""
    else:
        prompt = f"""Tu es un assistant intelligent de la SONACOS.
Tu dois répondre aux questions des employés en te basant UNIQUEMENT sur les documents officiels fournis.
Si la réponse n'est pas dans les documents, dis-le clairement.
Réponds toujours en français, même si les documents source sont dans une autre langue.

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
        "cannot find", "not found", "could not find", "no information"
    ]
    afficher_sources = not any(phrase in reponse.lower() for phrase in phrases_sans_source)

    return {
        'reponse': reponse,
        'sources': sources if afficher_sources else []
    }