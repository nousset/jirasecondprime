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

# Configuration des variables d'environnement
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY")
LM_STUDIO_BASE_URL = os.getenv("LM_STUDIO_API", "https://ventures-zu-richards-descriptions.trycloudflare.com")
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
        
        # Utiliser une nouvelle session pour éviter les problèmes de cache
        response = requests.get(LM_STUDIO_MODELS_URL, timeout=10)
        logger.info(f"Réponse: {response.status_code}")
        
        success = False
        if response.status_code == 200:
            # Vérifier que la réponse contient bien des modèles
            try:
                models_data = response.json()
                if "data" in models_data and len(models_data["data"]) > 0:
                    model_ids = [model.get('id') for model in models_data["data"]]
                    logger.info(f"Modèles disponibles: {model_ids}")
                    # Vérifier que notre modèle par défaut est disponible
                    if DEFAULT_MODEL in model_ids:
                        logger.info(f"Le modèle par défaut {DEFAULT_MODEL} est disponible")
                    success = True
                else:
                    logger.warning(f"Réponse valide mais sans modèles: {models_data}")
            except json.JSONDecodeError as e:
                logger.error(f"Erreur de décodage JSON: {e}, contenu: {response.text[:100]}")
        
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
    status = check_lm_studio_status()
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
        
        # Pour les requêtes de génération, utiliser directement requests sans la session avec retry
        # pour éviter des problèmes potentiels de timeout
        response = requests.post(LM_STUDIO_CHAT_URL, json=payload, headers=headers, timeout=120)
        
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
        model = data.get("model", DEFAULT_MODEL)
        
        if not story:
            return jsonify({"error": "Aucune user story fournie"}), 400

        # Vérifier d'abord l'état de LM Studio
        if not check_lm_studio_status():
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
            response = requests.post(LM_STUDIO_CHAT_URL, json=payload, headers=headers, timeout=30)
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
            
        response = requests.get(LM_STUDIO_MODELS_URL, timeout=10)
        if response.status_code == 200:
            models_data = response.json()
            # Ajouter le modèle par défaut
            return jsonify({
                "data": models_data.get("data", []),
                "default_model": DEFAULT_MODEL
            }), 200
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
    
    app.run(debug=True, port=5000)