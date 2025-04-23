import os
from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_cors import CORS
import requests
import json
import logging
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from functools import lru_cache
import time

# Configuration du logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="public", template_folder="template")
CORS(app)

# Constantes
HTML_INDEX = "index.html"
CONTENT_TYPE_JSON = "application/json"
DEFAULT_MODEL = "mistral-7b-instruct-v0.3"

# Configuration des variables d'environnement avec valeurs par défaut
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "")
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "")
# Correction: Utilisation d'une URL de fallback locale si la variable d'environnement n'est pas définie
LM_STUDIO_BASE_URL = os.getenv("LM_STUDIO_API", "https://cookbook-actively-specially-grove.trycloudflare.com")
APP_SECRET = os.getenv("APP_SECRET", "your-secret-key")

# URLs pour les APIs LM Studio
LM_STUDIO_MODELS_URL = f"{LM_STUDIO_BASE_URL}/v1/models"
LM_STUDIO_CHAT_URL = f"{LM_STUDIO_BASE_URL}/v1/chat/completions"

# Statut de disponibilité avec timestamp pour éviter trop de vérifications fréquentes
lm_studio_status = {
    "available": False,
    "last_check": 0,
    "check_interval": 60  # Vérifier au maximum toutes les 60 secondes
}

# Session HTTP avec retry - création singleton
@lru_cache(maxsize=1)
def get_http_session(retries=3, backoff_factor=0.3):
    """Crée et garde en cache une session HTTP avec retry"""
    session = requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=(500, 502, 504),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

# Vérification de l'état de LM Studio avec mise en cache
def check_lm_studio_status(force=False):
    """
    Vérifie si LM Studio est disponible en interrogeant l'API des modèles.
    Utilise un cache pour éviter des vérifications trop fréquentes.
    """
    global lm_studio_status
    current_time = time.time()
    
    # Si une vérification a été faite récemment et qu'on ne force pas, utiliser la valeur en cache
    if not force and (current_time - lm_studio_status["last_check"]) < lm_studio_status["check_interval"]:
        logger.debug(f"Utilisation du statut en cache: {lm_studio_status['available']}")
        return lm_studio_status["available"]
    
    try:
        logger.info(f"Vérification LM Studio à {LM_STUDIO_MODELS_URL}")
        
        # Utiliser une session avec retry pour plus de fiabilité
        session = get_http_session()
        # Augmenter le timeout et ajouter une vérification plus souple
        response = session.get(LM_STUDIO_MODELS_URL, timeout=15)
        logger.info(f"Réponse: {response.status_code}")
        
        success = response.status_code == 200
        
        # Correction: assouplir la vérification des modèles
        if success:
            try:
                models_data = response.json()
                if "data" in models_data and len(models_data["data"]) > 0:
                    model_ids = [model.get('id') for model in models_data["data"]]
                    logger.info(f"Modèles disponibles: {model_ids}")
                    
                    # Correction: Ne pas exiger que le modèle par défaut soit exactement présent
                    # Vérifier qu'il y a au moins un modèle disponible
                    if len(model_ids) > 0:
                        # Si notre modèle par défaut n'est pas disponible, utiliser le premier modèle disponible
                        if DEFAULT_MODEL not in model_ids:
                            logger.warning(f"Le modèle par défaut {DEFAULT_MODEL} n'est pas disponible, utilisation de {model_ids[0]}")
                            # Mettre à jour la variable globale
                            global DEFAULT_MODEL
                            DEFAULT_MODEL = model_ids[0]
                    else:
                        logger.warning("Aucun modèle disponible")
                        success = False
                else:
                    logger.warning(f"Réponse valide mais sans modèles: {models_data}")
                    success = False
            except json.JSONDecodeError as e:
                logger.error(f"Erreur de décodage JSON: {e}, contenu: {response.text[:100]}")
                success = False
        
        # Mettre à jour le statut
        lm_studio_status["available"] = success
        lm_studio_status["last_check"] = current_time
        return success
    except Exception as e:
        logger.error(f"Erreur lors de la vérification LM Studio : {type(e).__name__} - {e}")
        # Mettre à jour le statut en cas d'échec
        lm_studio_status["available"] = False
        lm_studio_status["last_check"] = current_time
        return False

# Construction du prompt - cache les prompts fréquents
@lru_cache(maxsize=32)
def build_prompt(story_text, format_choice, language="fr"):
    """Génère le prompt approprié selon le format et la langue choisis"""
    if language == "fr":
        if format_choice == "gherkin":
            return f"""Voici une user story : "{story_text}"
En tant qu'assistant de test, génère des scénarios de test au format Gherkin (Given/When/Then) en français.

Format attendu:
Feature: [Titre de la fonctionnalité]

  Scenario: [Titre du scénario 1]
    Given [condition préalable]
    When [action utilisateur]
    Then [résultat attendu]

  Scenario: [Titre du scénario 2]
    ...
"""
        else:
            return f"""Voici une user story : "{story_text}"
Génère des cas de test détaillés en français avec les étapes et résultats attendus.

Format attendu:
# Cas de test 1 : [Titre du cas de test]
## Action
[Description détaillée]

## Résultat attendu
[Description détaillée]

# Cas de test 2 : ...
"""
    else:
        if format_choice == "gherkin":
            return f"""Here is a user story: "{story_text}"
Generate test scenarios in Gherkin format (Given/When/Then) in English.

Expected format:
Feature: [Feature title]

  Scenario: [Scenario 1 title]
    Given [precondition]
    When [user action]
    Then [expected result]

  Scenario: [Scenario 2 title]
    ...
"""
        else:
            return f"""Here is a user story: "{story_text}"
Generate detailed test cases in English with steps and expected results.

Expected format:
# Test Case 1: [Title]
## Action
[Action description]

## Expected Result
[Expected outcome]

# Test Case 2: ...
"""

# Envoi du prompt à LM Studio
def generate_response(prompt, max_tokens=800, temperature=0.7, model=DEFAULT_MODEL):
    """Envoie un prompt à LM Studio et retourne la réponse générée"""
    # Forcer une vérification fraîche pour s'assurer que LM Studio est réellement disponible
    status = check_lm_studio_status(force=True)
    logger.info(f"Status LM Studio dans generate_response: {status}")
    
    if not status:
        logger.error("LM Studio n'est pas accessible")
        return "Erreur de connexion : LM Studio n'est pas accessible."

    headers = {"Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature
    }

    try:
        logger.info(f"Envoi d'une requête au modèle {model} à {LM_STUDIO_CHAT_URL}")
        
        # Utiliser la session HTTP avec retry pour plus de fiabilité
        session = get_http_session()
        # Augmenter le timeout pour les modèles plus lents
        response = session.post(LM_STUDIO_CHAT_URL, json=payload, headers=headers, timeout=180)
        
        if response.status_code != 200:
            logger.error(f"Erreur HTTP {response.status_code}: {response.text}")
            return f"Erreur HTTP {response.status_code}: Veuillez vérifier les logs pour plus de détails."
        
        # Extraction de la réponse
        result = response.json()
        if "choices" in result and len(result["choices"]) > 0:
            content = result["choices"][0]["message"]["content"]
            logger.info(f"Réponse générée avec succès ({len(content)} caractères)")
            return content
        else:
            logger.error(f"Format de réponse inattendu: {result}")
            return "Erreur: Format de réponse inattendu."
    except requests.exceptions.Timeout:
        logger.error("Timeout lors de la requête LM Studio")
        return "Timeout : le modèle met trop de temps à répondre."
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur requête LM Studio : {e}")
        return f"Erreur de requête : {str(e)}"
    except Exception as e:
        logger.error(f"Erreur inattendue lors de la génération: {type(e).__name__} - {e}")
        return f"Erreur inattendue: {str(e)}"

@app.route("/")
def home():
    """Page d'accueil de l'application"""
    return render_template(HTML_INDEX)

@app.route("/public/<path:path>")
def serve_public(path):
    """Sert les fichiers statiques du dossier public"""
    return send_from_directory("public", path)

@app.route("/static/<path:path>")
def serve_static(path):
    """Sert les fichiers statiques du dossier static"""
    return send_from_directory("static", path)

@app.route("/api/debug", methods=["GET"])
def api_debug():
    """Endpoint de débogage qui affiche les URLs configurées"""
    # Force une vérification fraîche
    status = check_lm_studio_status(force=True)
    
    return jsonify({
        "lm_studio_base_url": LM_STUDIO_BASE_URL,
        "models_url": LM_STUDIO_MODELS_URL,
        "chat_url": LM_STUDIO_CHAT_URL,
        "default_model": DEFAULT_MODEL,
        "env_var": os.getenv("LM_STUDIO_API", "non défini"),
        "models_check": status,
        "last_check": lm_studio_status["last_check"],
        "check_interval": lm_studio_status["check_interval"]
    }), 200

@app.route("/api/generate", methods=["POST"])
def api_generate():
    """Endpoint pour générer des tests à partir d'une user story"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Données JSON manquantes"}), 400
            
        story = data.get("story", "").strip()
        format_choice = data.get("format", "gherkin")
        language = data.get("language", "fr")
        # Correction: utiliser le modèle par défaut même s'il a été mis à jour
        model = data.get("model", DEFAULT_MODEL)
        
        if not story:
            return jsonify({"error": "Aucune user story fournie"}), 400

        # Vérifier d'abord l'état de LM Studio - forcer une vérification fraîche
        if not check_lm_studio_status(force=True):
            logger.error("LM Studio inaccessible lors de l'appel à api_generate")
            return jsonify({"error": "LM Studio n'est pas accessible. Veuillez vérifier la connexion et réessayer."}), 503

        # Générer et renvoyer les tests
        prompt = build_prompt(story, format_choice, language)
        logger.info(f"Envoi du prompt pour générer des tests (taille: {len(prompt)})")
        generated = generate_response(prompt, model=model)

        # Vérifier si la réponse est une erreur
        if generated.startswith("Erreur") or generated.startswith("Timeout"):
            return jsonify({"error": generated}), 500
            
        return jsonify({"result": generated})
    
    except Exception as e:
        logger.error(f"Erreur lors du traitement de la requête: {e}")
        return jsonify({"error": f"Erreur serveur: {str(e)}"}), 500

@app.route("/api/status", methods=["GET"])
def api_status():
    """Endpoint pour vérifier l'état de LM Studio"""
    # Force une vérification fraîche
    status = check_lm_studio_status(force=True)
    
    if status:
        return jsonify({
            "status": "LM Studio disponible", 
            "url": LM_STUDIO_BASE_URL,
            "default_model": DEFAULT_MODEL
        }), 200
    return jsonify({
        "status": "LM Studio non disponible", 
        "url": LM_STUDIO_BASE_URL
    }), 503

@app.route("/api/test_generation", methods=["GET"])
def test_generation():
    """Endpoint pour tester la génération avec un prompt fixe"""
    try:
        # Force une vérification fraîche
        if not check_lm_studio_status(force=True):
            return jsonify({"error": "LM Studio n'est pas accessible"}), 503
        
        test_prompt = "Générer un test simple pour un formulaire de login"
        headers = {"Content-Type": "application/json"}
        payload = {
            "model": DEFAULT_MODEL,
            "messages": [{"role": "user", "content": test_prompt}],
            "max_tokens": 100,
            "temperature": 0.7
        }
        
        logger.info(f"Test de génération à {LM_STUDIO_CHAT_URL}")
        
        try:
            # Utiliser la session HTTP avec retry
            session = get_http_session()
            response = session.post(LM_STUDIO_CHAT_URL, json=payload, headers=headers, timeout=30)
            logger.info(f"Réponse test: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                if "choices" in result and len(result["choices"]) > 0:
                    content = result["choices"][0]["message"]["content"]
                    return jsonify({
                        "success": True, 
                        "result": content,
                        "model": DEFAULT_MODEL
                    })
            
            # En cas d'échec, inclure les détails de la réponse
            return jsonify({
                "success": False, 
                "status_code": response.status_code, 
                "response": response.text
            }), 500
        except requests.exceptions.RequestException as e:
            logger.error(f"Erreur de requête: {e}")
            return jsonify({"error": f"Erreur de requête: {str(e)}"}), 500
    except Exception as e:
        logger.error(f"Erreur lors du test de génération: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/models", methods=["GET"])
def api_models():
    """Endpoint pour récupérer la liste des modèles disponibles"""
    try:
        # Force une vérification fraîche
        if not check_lm_studio_status(force=True):
            return jsonify({"error": "LM Studio n'est pas accessible"}), 503
            
        # Utiliser la session HTTP avec retry
        session = get_http_session()
        response = session.get(LM_STUDIO_MODELS_URL, timeout=10)
        
        if response.status_code == 200:
            try:
                models_data = response.json()
                # Ajouter le modèle par défaut
                return jsonify({
                    "data": models_data.get("data", []),
                    "default_model": DEFAULT_MODEL
                }), 200
            except json.JSONDecodeError as e:
                logger.error(f"Erreur de décodage JSON: {e}")
                return jsonify({"error": "Format de réponse invalide"}), 500
        return jsonify({"error": f"Erreur {response.status_code}"}), response.status_code
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des modèles: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/reset_connection", methods=["POST"])
def reset_connection():
    """Endpoint pour réinitialiser et forcer la connexion à LM Studio"""
    global lm_studio_status
    
    # Réinitialiser le statut
    lm_studio_status["available"] = False
    lm_studio_status["last_check"] = 0
    
    # Forcer une vérification fraîche
    status = check_lm_studio_status(force=True)
    
    return jsonify({
        "reset": True,
        "status": status,
        "message": "Connexion à LM Studio réinitialisée"
    }), 200

@app.route("/api/healthcheck", methods=["GET"])
def healthcheck():
    """Effectue une vérification complète du système"""
    try:
        # Vérifie LM Studio
        lm_status = check_lm_studio_status(force=True)
        
        # Teste une génération simple
        test_response = None
        if lm_status:
            test_prompt = "Test court"
            test_response = generate_response(test_prompt, max_tokens=10)
        
        return jsonify({
            "status": "ok" if lm_status else "error",
            "lm_studio": lm_status,
            "test_generation": test_response is not None and not test_response.startswith("Erreur")
        }), 200 if lm_status else 503
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# Nouveau endpoint pour tester manuellement la connexion à une URL spécifique
@app.route("/api/test_connection", methods=["POST"])
def test_connection():
    """Endpoint pour tester la connexion à une URL LM Studio spécifique"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Données JSON manquantes"}), 400
            
        test_url = data.get("url", "").strip()
        
        if not test_url:
            return jsonify({"error": "Aucune URL fournie"}), 400

        logger.info(f"Test de connexion à {test_url}")
        
        # Utiliser la session HTTP avec retry
        session = get_http_session()
        response = session.get(f"{test_url}/v1/models", timeout=10)
        
        return jsonify({
            "status_code": response.status_code,
            "success": response.status_code == 200,
            "content": response.text if len(response.text) < 500 else response.text[:500] + "..."
        }), 200
    except Exception as e:
        logger.error(f"Erreur lors du test de connexion: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # Vérifier la configuration au démarrage
    logger.info(f"LM Studio URL: {LM_STUDIO_BASE_URL}")
    logger.info(f"LM Studio Models URL: {LM_STUDIO_MODELS_URL}")
    logger.info(f"LM Studio Chat URL: {LM_STUDIO_CHAT_URL}")
    logger.info(f"Modèle par défaut: {DEFAULT_MODEL}")
    
    # Vérifier si LM Studio est disponible
    if check_lm_studio_status(force=True):
        logger.info("LM Studio est disponible")
    else:
        logger.warning("LM Studio n'est pas disponible au démarrage. Vérifiez la connexion.")
    
    # Utiliser environment variable PORT si disponible, sinon 5000
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)