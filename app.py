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
import base64

# Configuration du logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="public", template_folder="template")
# Activer CORS avec des options plus permissives pour éviter les problèmes de timeout
CORS(app, supports_credentials=True, resources={
    r"/api/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

# Constantes
HTML_INDEX = "index.html"
CONTENT_TYPE_JSON = "application/json"
DEFAULT_MODEL = "deepseek-r1-distill-qwen-7b"

# Configuration des variables d'environnement avec valeurs par défaut
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "")
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "")
# Correction: Utilisation d'une URL de fallback locale si la variable d'environnement n'est pas définie
LM_STUDIO_BASE_URL = os.getenv("LM_STUDIO_API", "https://concentrations-strange-achieve-w.trycloudflare.com")

# S'assurer que l'URL ne se termine pas par un slash
if LM_STUDIO_BASE_URL.endswith('/'):
    LM_STUDIO_BASE_URL = LM_STUDIO_BASE_URL[:-1]

APP_SECRET = os.getenv("APP_SECRET", "your-secret-key")

# URLs pour les APIs LM Studio
LM_STUDIO_MODELS_URL = f"{LM_STUDIO_BASE_URL}/v1/models"
LM_STUDIO_CHAT_URL = f"{LM_STUDIO_BASE_URL}/v1/chat/completions"

lm_studio_status = {
    "available": False,
    "last_check": 0,
    "check_interval": 60  # Vérifier au maximum toutes les 60 secondes
}

# Session HTTP avec retry - création singleton
@lru_cache(maxsize=1)
def get_http_session(retries=5, backoff_factor=0.5):
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
    global lm_studio_status, DEFAULT_MODEL  
    current_time = time.time()
    
    # Si une vérification a été faite récemment et qu'on ne force pas, utiliser la valeur en cache
    if not force and (current_time - lm_studio_status["last_check"]) < lm_studio_status["check_interval"]:
        logger.debug(f"Utilisation du statut en cache: {lm_studio_status['available']}")
        return lm_studio_status["available"]
    
    try:
        logger.info(f"Vérification LM Studio à {LM_STUDIO_MODELS_URL}")
        
        # Utiliser une session avec retry pour plus de fiabilité
        session = get_http_session()
        # Augmenter le timeout et utiliser des paramètres de vérification plus souples
        response = session.get(LM_STUDIO_MODELS_URL, timeout=30)  # Augmentation du timeout à 30s
        logger.info(f"Réponse status: {response.status_code}")
        
        success = response.status_code == 200
        
        # Assouplir la vérification des modèles
        if success:
            try:
                models_data = response.json()
                logger.info(f"Données modèles reçues: {models_data}")
                
                if "data" in models_data and len(models_data["data"]) > 0:
                    model_ids = [model.get('id') if isinstance(model, dict) else model for model in models_data["data"]]
                    logger.info(f"Modèles disponibles: {model_ids}")
                    
                    # Si aucun modèle n'est disponible, c'est une erreur
                    if not model_ids:
                        logger.warning("Aucun modèle disponible")
                        success = False
                        return success
                    
                    # Si notre modèle par défaut n'est pas disponible, utiliser le premier modèle
                    if DEFAULT_MODEL not in model_ids:
                        logger.warning(f"Le modèle par défaut {DEFAULT_MODEL} n'est pas disponible, utilisation de {model_ids[0]}")
                        DEFAULT_MODEL = model_ids[0]
                else:
                    logger.warning(f"Réponse valide mais sans modèles: {models_data}")
                    success = False
            except json.JSONDecodeError as e:
                logger.error(f"Erreur de décodage JSON: {e}, contenu: {response.text[:200]}")
                success = False
        
        # Mettre à jour le statut
        lm_studio_status["available"] = success
        lm_studio_status["last_check"] = current_time
        return success
    except Exception as e:
        logger.error(f"Erreur lors de la vérification LM Studio : {type(e).__name__} - {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
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
    
    # CORRECTION 1: Augmenter max_tokens pour éviter les troncatures
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens * 2,  # Doubler pour éviter les troncatures
        "temperature": temperature,
        "stream": False
    }

    # Délai exponentiel entre les tentatives
    for attempt in range(3):  # Essayez jusqu'à 3 fois
        try:
            logger.info(f"Tentative {attempt+1} pour envoyer une requête au modèle {model}")
            logger.info(f"Envoi d'une requête au modèle {model} à {LM_STUDIO_CHAT_URL}")
            logger.info(f"Payload: {json.dumps(payload)}")
            
            # Utiliser la session HTTP avec retry pour plus de fiabilité
            session = get_http_session(retries=5)  # Augmenter le nombre de retries
            
            # CORRECTION 3: Augmenter le timeout pour les modèles plus lents
            response = session.post(LM_STUDIO_CHAT_URL, json=payload, headers=headers, timeout=600)  # 10 minutes max
            
            if response.status_code == 200:
                # Extraction de la réponse avec validation
                try:
                    result = response.json()
                    logger.info(f"Structure de la réponse: {json.dumps(result, indent=2)[:200]}...")
                    
                    if "choices" in result and len(result["choices"]) > 0:
                        if "message" in result["choices"][0] and "content" in result["choices"][0]["message"]:
                            content = result["choices"][0]["message"]["content"]
                            logger.info(f"Réponse générée avec succès ({len(content)} caractères)")
                            return content
                        else:
                            logger.error(f"Format de choix inattendu: {result['choices'][0]}")
                            return f"Erreur: Format de réponse incomplet ou inattendu."
                    else:
                        logger.error(f"Format de réponse inattendu: {result}")
                        return "Erreur: Format de réponse inattendu."
                except json.JSONDecodeError as e:
                    logger.error(f"Erreur de décodage JSON: {e}, contenu: {response.text[:200]}")
                    return f"Erreur de décodage: {str(e)}"
            
            # En cas d'erreur, attendre avant de réessayer
            if attempt < 2:  # Ne pas attendre après la dernière tentative
                wait_time = (2 ** attempt) * 2  # 2, 4, 8 secondes
                logger.warning(f"Erreur {response.status_code}, nouvelle tentative dans {wait_time}s")
                time.sleep(wait_time)
            else:
                logger.error(f"Échec définitif après {attempt+1} tentatives. Code: {response.status_code}, Réponse: {response.text}")
                return f"Erreur HTTP {response.status_code}: Veuillez vérifier les logs pour plus de détails."
                
        except requests.exceptions.Timeout:
            if attempt < 2:  # Ne pas attendre après la dernière tentative
                wait_time = (2 ** attempt) * 5  # 5, 10, 20 secondes
                logger.warning(f"Timeout, nouvelle tentative dans {wait_time}s")
                time.sleep(wait_time)
            else:
                logger.error("Timeout définitif après 3 tentatives")
                return "Timeout : le modèle met trop de temps à répondre. Essayez de réduire la complexité de votre requête."
        except requests.exceptions.RequestException as e:
            logger.error(f"Erreur requête LM Studio : {e}")
            return f"Erreur de requête : {str(e)}"
        except Exception as e:
            logger.error(f"Erreur inattendue lors de la génération: {type(e).__name__} - {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return f"Erreur inattendue: {str(e)}"
    
    # Si on arrive ici, c'est que toutes les tentatives ont échoué
    return "Erreur: Impossible d'obtenir une réponse après plusieurs tentatives."
    
     
def clean_response(content):
    """Supprime les balises <think> de la réponse du modèle"""
    import re
    return re.sub(r'<think>.*?</think>\s*', '', content, flags=re.DOTALL).strip()

# Fonctions pour Jira
def check_jira_credentials():
    """Vérifie si les identifiants Jira sont configurés"""
    return all([JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_PROJECT_KEY])

def create_jira_auth_header():
    """Crée l'en-tête d'authentification pour les requêtes Jira"""
    if not check_jira_credentials():
        logger.error("Identifiants Jira non configurés")
        return None
        
    credentials = f"{JIRA_EMAIL}:{JIRA_API_TOKEN}"
    encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
    return {
        "Authorization": f"Basic {encoded_credentials}",
        "Content-Type": "application/json"
    }

def parse_test_cases(generated_content, format_choice):
    """
    Analyse le contenu généré pour extraire les cas de test individuels
    """
    test_cases = []
    
    if format_choice == "gherkin":
        # Pour le format Gherkin, diviser en scénarios
        if "Scenario:" in generated_content:
            # Diviser par "Scenario:" mais garder l'en-tête "Feature:"
            parts = generated_content.split("Scenario:")
            feature_part = parts[0].strip()
            feature_name = ""
            
            # Extraire le nom de la fonctionnalité
            if "Feature:" in feature_part:
                feature_name = feature_part.split("Feature:")[1].strip()
            
            # Traiter chaque scénario
            for i, scenario_part in enumerate(parts[1:], 1):
                # Récupérer la première ligne comme titre du scénario
                scenario_lines = scenario_part.strip().split("\n")
                scenario_title = scenario_lines[0].strip() if scenario_lines else f"Scénario {i}"
                scenario_content = "Scenario:" + scenario_part.strip()
                
                test_cases.append({
                    "title": f"{feature_name} - {scenario_title}",
                    "description": scenario_content
                })
    else:
        # Pour le format standard, diviser par "# Cas de test" ou équivalent
        if "# Cas de test" in generated_content or "# Test Case" in generated_content:
            # Diviser par les titres de cas de test
            import re
            test_case_pattern = r"# (?:Cas de test|Test Case).*?(?=# (?:Cas de test|Test Case)|$)"
            matches = re.findall(test_case_pattern, generated_content, re.DOTALL)
            
            for match in matches:
                # Extraire le titre du cas de test
                title_match = re.search(r"# (?:Cas de test|Test Case)\s*\d*\s*:?\s*(.*?)(?:\n|$)", match)
                title = title_match.group(1).strip() if title_match else "Cas de test"
                
                test_cases.append({
                    "title": title,
                    "description": match.strip()
                })
    
    return test_cases

def create_jira_issue(title, description, issue_type="Task"):
    """
    Crée une issue dans Jira avec le titre et la description fournis
    """
    if not check_jira_credentials():
        logger.error("Identifiants Jira non configurés")
        return {"error": "Configuration Jira incomplète"}, 400
    
    # Créer l'URL de l'API
    api_url = f"{JIRA_BASE_URL}/rest/api/2/issue/"
    
    # Préparer les en-têtes
    headers = create_jira_auth_header()
    if not headers:
        return {"error": "Erreur d'authentification Jira"}, 401
    
    # Préparer les données
    payload = {
        "fields": {
            "project": {
                "key": JIRA_PROJECT_KEY
            },
            "summary": title,
            "description": description,
            "issuetype": {
                "name": issue_type
            }
        }
    }
    
    try:
        # Envoyer la requête à Jira
        logger.info(f"Création d'une issue Jira: {title}")
        session = get_http_session()
        response = session.post(api_url, json=payload, headers=headers, timeout=30)
        
        # Traiter la réponse
        if response.status_code in [200, 201]:
            issue_data = response.json()
            logger.info(f"Issue Jira créée avec succès: {issue_data.get('key')}")
            return {
                "success": True,
                "issue_key": issue_data.get('key'),
                "issue_url": f"{JIRA_BASE_URL}/browse/{issue_data.get('key')}"
            }, 201
        else:
            logger.error(f"Erreur lors de la création de l'issue Jira: {response.status_code} - {response.text}")
            return {
                "success": False,
                "error": f"Erreur {response.status_code}: {response.text}"
            }, response.status_code
    except Exception as e:
        logger.error(f"Exception lors de la création de l'issue Jira: {str(e)}")
        return {"success": False, "error": str(e)}, 500

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
        "check_interval": lm_studio_status["check_interval"],
        "jira_configured": check_jira_credentials()
    }), 200

@app.route("/api/debug/lm_studio", methods=["GET"])
def debug_lm_studio():
    """Endpoint spécifique pour déboguer la connexion LM Studio"""
    try:
        # Test basique avec une requête simplifiée
        test_url = f"{LM_STUDIO_BASE_URL}/v1/models"
        session = get_http_session(retries=1)
        
        # Test avec un timeout court
        response = None
        try:
            response = session.get(test_url, timeout=5)
            response_data = {
                "status_code": response.status_code,
                "response_text": response.text[:500],  # Limiter la taille
            }
            if response.status_code == 200:
                try:
                    response_data["json"] = response.json()
                except:
                    response_data["json_error"] = "Impossible de parser le JSON"
        except Exception as e:
            response_data = {"error": str(e)}
            
        return jsonify({
            "lm_studio_url": LM_STUDIO_BASE_URL,
            "test_url": test_url,
            "response": response_data,
            "env_settings": {
                "LM_STUDIO_API": os.getenv("LM_STUDIO_API", "non défini"),
                "DEFAULT_MODEL": DEFAULT_MODEL,
            }
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
        create_jira_tasks = data.get("create_jira_tasks", False)
        
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
        
        # Si demandé, créer des tâches Jira
        jira_issues = []
        if create_jira_tasks:
            if not check_jira_credentials():
                return jsonify({
                    "result": generated,
                    "jira_error": "Configuration Jira incomplète. Veuillez configurer les variables d'environnement Jira."
                }), 200
            
            # Extraire les cas de test individuels
            test_cases = parse_test_cases(generated, format_choice)
            logger.info(f"Création de {len(test_cases)} tâches Jira")
            
            # Créer une tâche Jira pour chaque cas de test
            for test_case in test_cases:
                result, status_code = create_jira_issue(
                    title=f"Test: {test_case['title']}",
                    description=f"User Story: {story}\n\n{test_case['description']}"
                )
                jira_issues.append(result)
                
                # En cas d'erreur, logger mais continuer
                if not result.get("success", False) and status_code >= 400:
                    logger.error(f"Erreur lors de la création d'une tâche Jira: {result}")
            
        # Retourner le résultat
        response_data = {"result": generated}
        if create_jira_tasks:
            response_data["jira_issues"] = jira_issues
            
        return jsonify(response_data)
    
    except Exception as e:
        logger.error(f"Erreur lors du traitement de la requête: {e}")
        return jsonify({"error": f"Erreur serveur: {str(e)}"}), 500
    
@app.route("/api/ping", methods=["GET"])
def ping():
    """Simple ping pour vérifier que l'application fonctionne"""
    return jsonify({"status": "ok", "message": "pong"}), 200

@app.route("/api/jira/status", methods=["GET"])
def check_jira_status():
    """Vérifie si Jira est configuré et accessible"""
    if not check_jira_credentials():
        return jsonify({
            "configured": False,
            "error": "Configuration Jira incomplète"
        }), 200
    
    try:
        # Tester la connexion à Jira
        api_url = f"{JIRA_BASE_URL}/rest/api/2/serverInfo"
        headers = create_jira_auth_header()
        
        session = get_http_session()
        response = session.get(api_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            server_info = response.json()
            return jsonify({
                "configured": True,
                "connected": True,
                "server_title": server_info.get("serverTitle", "Jira"),
                "base_url": JIRA_BASE_URL,
                "project_key": JIRA_PROJECT_KEY
            }), 200
        else:
            return jsonify({
                "configured": True,
                "connected": False,
                "error": f"Erreur de connexion: {response.status_code}",
                "base_url": JIRA_BASE_URL
            }), 200
    except Exception as e:
        return jsonify({
            "configured": True,
            "connected": False,
            "error": str(e),
            "base_url": JIRA_BASE_URL
        }), 200
    
@app.route("/api/jira/create_test_issues", methods=["POST"])
def create_jira_test_issues():
    """Endpoint pour créer des tâches Jira à partir de cas de test déjà générés"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Données JSON manquantes"}), 400
            
        generated_content = data.get("generated_content", "").strip()
        format_choice = data.get("format", "gherkin")
        story = data.get("story", "User story non spécifiée").strip()
        
        if not generated_content:
            return jsonify({"error": "Aucun contenu généré fourni"}), 400
            
        # Vérifier si Jira est configuré
        if not check_jira_credentials():
            return jsonify({"error": "Configuration Jira incomplète"}), 400
            
        # Extraire les cas de test individuels
        test_cases = parse_test_cases(generated_content, format_choice)
        logger.info(f"Création de {len(test_cases)} tâches Jira")
        
        # Créer une tâche Jira pour chaque cas de test
        jira_issues = []
        for test_case in test_cases:
            result, status_code = create_jira_issue(
                title=f"Test: {test_case['title']}",
                description=f"User Story: {story}\n\n{test_case['description']}"
            )
            jira_issues.append(result)
            
        return jsonify({"issues": jira_issues})
    except Exception as e:
        logger.error(f"Erreur lors de la création des tâches Jira: {e}")
        return jsonify({"error": str(e)}), 500
   
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

@app.route("/api/save_history", methods=["POST"])
def save_history():
    """Endpoint pour sauvegarder l'historique des conversations"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Données JSON manquantes"}), 400
            
        # Implémentez la logique de sauvegarde de l'historique
        # Par exemple, vous pourriez stocker les données dans une base de données
        # ou dans un fichier JSON
        
        # Exemple simple de journalisation des données
        logger.info(f"Sauvegarde de l'historique: {len(data)} éléments")
        
        return jsonify({"success": True}), 200
    except Exception as e:
        logger.error(f"Erreur lors de la sauvegarde de l'historique: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/test_generation", methods=["GET", "POST"])
def test_generation():
    """Endpoint pour tester la génération avec un prompt fixe"""
    try:
        # Vérifier la méthode HTTP
        if request.method == "GET":
            # Simplement retourner un formulaire de test
            return jsonify({
                "message": "Utilisez une requête POST pour tester la génération"
            }), 200
        
        # Pour les requêtes POST, effectuer un test de génération
        # Vérifier d'abord l'état de LM Studio
        if not check_lm_studio_status(force=True):
            return jsonify({
                "error": "LM Studio n'est pas accessible pour le test"
            }), 503
        
        # Utiliser un prompt de test simple
        test_prompt = "Générer un exemple de cas de test pour une fonctionnalité de login"
        result = generate_response(test_prompt)
        
        return jsonify({
            "success": True,
            "test_result": result,
            "lm_studio_status": lm_studio_status
        }), 200
        
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
                raw_models = models_data.get("data", [])

                # Helper pour rendre le nom joli
                def format_model_name(model_id: str) -> str:
                    return model_id.replace("-", " ").replace("_", " ").title()

                formatted_models = []

                for model in raw_models:
                    if isinstance(model, str):
                        formatted_models.append({
                            "id": model,
                            "name": format_model_name(model)
                        })
                    elif isinstance(model, dict):
                        model_id = model.get("id") or model.get("name") or str(model)
                        model_name = model.get("name") or model_id
                        formatted_models.append({
                            "id": model_id,
                            "name": format_model_name(model_name)
                        })
                    else:
                        logger.warning(f"Modèle non reconnu: {model}")

                return jsonify({
                    "data": formatted_models,
                    "default_model": DEFAULT_MODEL
                }), 200

            except json.JSONDecodeError as e:
                logger.error(f"Erreur de décodage JSON: {e}")
                return jsonify({"error": "Format de réponse invalide"}), 500

        return jsonify({"error": f"Erreur {response.status_code}"}), response.status_code

    except Exception as e:
        logger.error(f"Erreur lors de la récupération des modèles: {e}")
        return jsonify({"error": str(e)}), 500



# Point d'entrée principal pour l'exécution de l'application
if __name__ == "__main__":
    # Configuration du port pour l'application
    port = int(os.getenv("PORT", 5000))
    
    # Vérifier la disponibilité de LM Studio au démarrage
    logger.info("Vérification de la disponibilité de LM Studio au démarrage...")
    lm_studio_available = check_lm_studio_status(force=True)
    if lm_studio_available:
        logger.info(f"LM Studio accessible à {LM_STUDIO_BASE_URL}, modèle par défaut: {DEFAULT_MODEL}")
    else:
        logger.warning(f"LM Studio non accessible à {LM_STUDIO_BASE_URL}. Vérifiez la configuration.")
    
    # Afficher les informations de configuration Jira
    if check_jira_credentials():
        logger.info(f"Configuration Jira valide pour le projet {JIRA_PROJECT_KEY} à {JIRA_BASE_URL}")
    else:
        logger.warning("Configuration Jira incomplète. Les fonctionnalités Jira seront désactivées.")
    
    # Démarrer l'application
    logger.info(f"Démarrage de l'application sur le port {port}...")
    app.run(host="0.0.0.0", port=port, debug=True)