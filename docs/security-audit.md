# Audit de sécurité du 26 octobre 2026

## Périmètre et résultat

Revue du code de l'API, des services et dépôts SQL, de l'authentification, du BFF SvelteKit,
des profils et permissions, des cours, des fichiers, des migrations, des configurations Docker,
du proxy fourni et de la CI. Vérifications dynamiques sur des données synthétiques dans des
services Docker jetables. Aucun accès à une installation de production.

La suppression de l'antivirus est réalisée conformément à la décision de faire confiance aux
enseignants. Les validations de format, quotas et autorisations restent actives. Aucun changement
de schéma, de table ou de migration n'est nécessaire pour cette modification.

Les tests exercés ne montrent pas de contournement des sessions ou des autorisations documentaires.
Un défaut de fermeture de fichier sous annulation a été reproduit puis corrigé. Le mainteneur a
explicitement confirmé les choix du secret bootstrap permissif, de l'absence de MFA pour le moment
et du catalogue global. Ces points restent décrits pour expliquer le modèle de confiance accepté.
Les autres constats ci-dessous comprennent des risques résiduels et des
choix de politique existants, à distinguer de failles exploitées.

HTTPS est prévu pour la production et n'est pas ajouté par cet incrément. Les certificats,
redirections, HSTS, paramètres du proxy réel, ACL de l'hôte et sauvegardes restent à vérifier
sur le déploiement. Ce rapport ne certifie pas une sécurité exhaustive ni l'aptitude à la production.

## Constats classés par priorité

| Référence | Priorité | Constat | État |
| --- | --- | --- | --- |
| SEC-01 | Risque élevé conditionnel accepté | Secret bootstrap vide ou faible accepté | Choix confirmé par le mainteneur |
| SEC-02 | Risque moyen accepté pour ce périmètre | Résistance limitée aux attaques de connexion distribuées et au vol de mots de passe | Absence de MFA confirmée pour la taille actuelle du site |
| SEC-03 | Concurrence corrigée ; débit résiduel | Téléchargements avec plafond global et file d'attente | Aucun plafond par compte ; débit et taille de file non bornés |
| SEC-04 | Moyenne | Analyseurs de fichiers exécutés avec les privilèges du backend | Isolation supplémentaire à étudier |
| SEC-05 | Politique acceptée | Catalogue global et lecture de tous les enseignants | Choix confirmé par le mainteneur |
| SEC-06 | Moyenne | Versions Python et images non verrouillées ; audit de dépendances absent de la CI | Reproductibilité et suivi à améliorer |
| SEC-07 | Faible | Absence de CSP et protections HTTP incomplètes sur les erreurs précoces | Défense supplémentaire à préparer |
| SEC-08 | Faible à moyenne selon exploitation | Rétention, journaux du proxy et supervision à configurer | Mesures d'exploitation non vérifiées |
| SEC-09 | Moyenne | Fermeture de fichier interrompue lors d'une annulation | Corrigé et testé |
| TRUST-01 | Risque accepté | Un document valide peut rester malveillant pour son destinataire | Suppression de l'antivirus explicitement demandée |

### SEC-01 — Secret d'installation vide ou faible

Preuves : `backend/app/core/security_policy.py::read_bootstrap_password`,
`backend/app/schemas/auth.py::LoginRequest`,
`backend/app/services/auth.py::initialize_installation` et
`backend/tests/test_auth_postgres.py::test_automatic_bootstrap_and_renewal`.
Le chargeur accepte une chaîne vide ou `simple`, et la connexion autorise une longueur nulle.
Les tests exigent explicitement ce comportement. Le mode production ne renforce pas ce secret.

Si un opérateur fournit un fichier vide/faible avant le premier démarrage et expose le site,
une personne connaissant ou devinant l'identifiant bootstrap peut terminer l'installation à sa place.
La restriction des routes du compte bootstrap limite ses opérations, mais autorise précisément
la création du premier administrateur. L'expiration à 48 heures limite la durée, pas ce risque.

Recommandation : exiger un secret d'installation robuste avant initialisation et renouvellement,
au moins en production ; garder la possibilité d'un fichier vide après installation terminée,
car il n'est alors plus lu. À défaut, effectuer l'installation sur un accès privé avant ouverture.
La politique n'est pas changée dans cet incrément, pour ne pas modifier silencieusement le parcours
explicitement couvert par les tests existants. L'état ou le secret réel de l'installation n'a pas été lu.

### SEC-02 — Connexions distribuées et comptes privilégiés

Preuves : `backend/app/services/auth.py::login`, `AuthService._limit`,
`backend/app/repositories/auth.py::reserve_login` et `backend/app/core/auth_config.py`.
Le budget de connexion combine IP et couple IP/identifiant normalisé. Les noms d'utilisateur et
adresses email sont des clés distinctes. Des IP différentes n'épuisent pas un budget global du compte.
Il n'existe pas de second facteur ni de vérification contre une liste de mots de passe compromis.
La politique permanente impose 10 à 128 caractères ASCII et quatre catégories.

Un attaquant distribué conserve donc davantage d'essais ; un mot de passe volé reste suffisant.
Les budgets persistants, réponses génériques et limites Argon2 sont utiles et ne sont pas contournés
par un simple en-tête de proxy dans la configuration prévue. Aucune attaque distribuée de charge
n'a été lancée. Prévoir un second facteur pour les administrateurs/enseignants et une politique de
détection ou de budget par compte, en tenant compte du risque de blocage malveillant des utilisateurs.
Ces choix demandent une conception dédiée ; aucun verrouillage global n'est ajouté ici.
Voir [OWASP Authentication](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
et [OWASP MFA](https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html).

### SEC-03 — Coût des téléchargements

Mise à jour après validation du mainteneur : les téléchargements sont désormais limités globalement
par `DOCUMENT_MAX_CONCURRENT_DOWNLOADS`, défini dans le `.env` et transmis par Compose (16 par défaut).
Les demandes supplémentaires attendent en FIFO, sans limite par compte et sans ouverture de fichier
ni transaction SQL pendant l'attente. Les droits sont revérifiés après admission. Le créneau reste
réservé jusqu'à la fin du flux et est libéré sur erreur/annulation/déconnexion. Les clients déconnectés
sont retirés de la file. Le plafond concerne le processus backend unique de Compose ; il faudrait
une coordination partagée pour plusieurs processus ou réplicas.

Le BFF laisse attendre les téléchargements et propage l'annulation du navigateur. Le fragment Nginx
prévoit un délai de lecture de 3600 secondes et désactive le buffering pour cette route. Les délais
des clients et transports HTTP restent applicables. La limite ne fixe pas un débit réseau maximal,
ne borne pas la taille de la file d'attente et ne remplace pas une protection contre un DDoS.

Constat initial, avant ce correctif :

Preuves : `backend/app/services/lesson_documents.py::download`,
`frontend/src/lib/server/lessonFiles.ts::transferLessonFile`, `infra/nginx.conf`.
Chaque demande autorisée parcourt le cours et relit le fichier pour vérifier son SHA-256 avant
de l'envoyer. Cette vérification reste dans la transaction d'autorisation. Les fichiers sont bornés
à 50 Mio et les flux du BFF ont une échéance, mais il n'existe pas de budget dédié par utilisateur/IP,
ni de plafond de téléchargements concurrents dans le proxy fourni.

Un utilisateur autorisé peut multiplier les lectures disque, connexions SQL et transferts pour
dégrader la disponibilité. Aucun accès supplémentaire à un document ne lui est accordé.
Le budget global de concurrence est maintenant appliqué ; la limitation de bande passante reste
distincte. Les vérifications d'accès et d'intégrité sont conservées. Aucun test de saturation de
l'hôte n'a été réalisé.

### SEC-04 et TRUST-01 — Analyse de structure et confiance dans les enseignants

Preuves : `backend/app/services/document_storage.py::validate`,
`backend/app/services/file_validation.py` et `backend/Dockerfile`.
Le processus d'analyse a une limite de 30 secondes ; sous Linux, 512 Mio d'espace d'adressage
et 20 secondes CPU. Il utilise néanmoins le même utilisateur, l'environnement et les montages
du backend. C'est une limitation de ressources, pas une isolation de sécurité entre l'analyseur
et les secrets du backend. Une vulnérabilité d'un parseur pourrait donc avoir un impact sur l'API.

Un service d'analyse séparé, sans secrets ni réseau et avec des droits minimaux sur les fichiers,
serait un durcissement possible. Il n'est pas introduit par cet incrément. Maintenir les parseurs
à jour reste nécessaire même avec des déposants de confiance.

Sans antivirus, les validations ne détectent pas tous les PDF actifs, les exécutables dissimulés
dans un ZIP, les polyglottes ou les contenus trompeurs. Les archives ne sont pas extraites et
aucun Python déposé n'est exécuté par Sophikron ; l'ouverture sur le poste d'un destinataire
reste un risque distinct. Une compromission d'un compte enseignant suffit à exploiter cette confiance.
Le téléchargement forcé protège le rendu dans le site, pas l'ouverture locale du document.
Voir [OWASP File Upload](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html).

### SEC-05 — Visibilité métier des cours

Preuves : `backend/app/services/lessons.py::catalogue`, `LessonService._card`,
`LessonService._detail` et `docs/lessons.md`.
Le catalogue donne les titres, descriptions et noms des intervenants de tous les cours aux comptes
permanents authentifiés, même sans droit d'ouvrir le cours. Tous les enseignants/administrateurs
ont la lecture complète, y compris l'audience `staff` et hors dates. Les khôlleurs collaborateurs
ont également cette lecture ; les élèves restent filtrés par promotion, audience et dates.

Il s'agit de la politique actuelle documentée et testée. Un cours fermé à une promotion n'a donc
pas des métadonnées confidentielles vis-à-vis des autres comptes. Ne pas placer d'informations
sensibles dans ces titres/descriptions en supposant qu'ils sont privés. Si « cours privé » doit
signifier invisible hors de son équipe ou de ses promotions, changer ensemble catalogue, API,
interface et tests après validation de cette nouvelle règle.

### SEC-06 — Dépendances et chaîne de construction

Preuves : `backend/pyproject.toml`, `backend/Dockerfile`, `frontend/Dockerfile`,
`frontend/package-lock.json` et `.github/workflows/ci.yml`.
Le frontend possède un verrou npm ; le backend résout des plages de versions, certaines sans
borne supérieure. Les images de base et actions CI utilisent des étiquettes mutables. Le build
Docker de cet audit a installé FastAPI 0.162.0 et Starlette 1.10.0, alors que l'interpréteur local
utilise respectivement 0.146.0 et 1.9.0. Un test local ne vérifie donc pas exactement le même ensemble.

Prévoir un verrouillage Python reproductible et des mises à jour revues, puis un contrôle des
avis de sécurité en CI et un scan des images réellement livrées. Aucune nouvelle dépendance de
production ni nouvel outil permanent n'est installé pour cet audit.

Contrôles effectués :

- `npm audit --json` : aucune vulnérabilité signalée sur les 196 dépendances inventoriées.
- Interrogation de l'API JSON PyPI pour les 54 distributions installées dans l'interpréteur local,
  hors paquet du projet : toutes les requêtes ont abouti. Aucun avis sur les autres versions examinées.
- PyPI/OSV signale `GHSA-6q48-6c7w-9gw2` / `PYSEC-2026-4320` pour `certifi==2026.10.18`.
  La [publication officielle de Certifi](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2)
  indique toutefois 2026.10.18 comme version corrigée. L'inspection effective du bundle local confirme
  l'absence de certificats emSign. L'alerte n'est donc pas classée comme vulnérabilité critique
  confirmée sur cet environnement ; les métadonnées des sources divergent et restent à suivre.

L'interrogation PyPI est une vérification des avis associés aux versions, pas une analyse du code
des dépendances. Les paquets système des images, les dépendances propres à Linux et le runtime
de production ne sont pas couverts par ce contrôle local. Les versions installées ne sont pas modifiées.

### SEC-07 — Protection du navigateur

Preuves : `frontend/src/hooks.server.ts`, `frontend/vite.config.ts`,
`frontend/src/lib/components/lessons/FormattedText.svelte`.
Le texte reste échappé, sans rendu HTML utilisateur identifié. Les couleurs sont validées et
les lecteurs YouTube sont construits depuis un identifiant vérifié. Aucun XSS n'a été reproduit.
Il n'y a néanmoins pas de CSP fournie par le projet. Les réponses précoces de refus dans le hook
ne passent pas par l'ajout final de `nosniff`, `X-Frame-Options` et `Referrer-Policy`.

Préparer une CSP compatible avec SvelteKit, ses scripts et le lecteur YouTube, éventuellement
en mode rapport avant application ; homogénéiser les en-têtes sur les erreurs. Les protections
actuelles ne remplacent pas la prévention d'une future injection de script.

### SEC-08 — Exploitation, conservation et secrets

Preuves : `backend/app/cli.py::execute`, `backend/app/core/http.py::SearchAccessLogFilter`,
`infra/nginx.conf`, `compose.yaml` et `docs/lesson-documents.md`.
La purge des compteurs de connexion existe via `prune-rate-limits`, sans planification dans Compose.
La conservation des anciennes sessions, invitations, événements et sauvegardes nécessite une
politique d'exploitation. La maintenance documentaire réessaie les suppressions et purge les
orphelins anciens ; une panne disque ou une file en échec peut différer la suppression physique.

Le filtre Uvicorn retire les recherches nominatives connues, mais le fragment Nginx ne définit
pas un format de journal excluant les paramètres des recherches du BFF. Avec un journal hérité
en format usuel, ces URL peuvent contenir du texte personnel. Vérifier le proxy réel, limiter
l'accès aux journaux et définir leur rétention. Aucun journal de production n'a été consulté.

Les secrets sont des fichiers montés, exclus du contexte Docker par les règles d'ignore ; leurs
valeurs ne sont pas affichées. Le rôle SQL applicatif n'est ni propriétaire ni superutilisateur,
mais peut accéder aux données applicatives : le chiffrement des identités ne protège pas contre
la compromission d'un backend qui possède aussi les clés. Les documents ne sont pas chiffrés
par l'application au repos. Protéger hôte, volumes, secrets et sauvegardes ; tester une restauration
cohérente base/fichiers/clés. Aucune inspection de l'historique Git n'a été faite.

### SEC-09 — Fermeture annulable du flux de téléchargement, corrigée

Preuve : `backend/app/api/v1/lesson_documents.py::download`.
Le `finally` du générateur appelait `await source.aclose()` dans la portée d'annulation du flux.
Sous annulation AnyIO, cet appel pouvait être interrompu avant fermeture. Le test
`test_cancelled_download_closes_the_open_file` a d'abord échoué avec un vrai fichier encore ouvert.
La fermeture est maintenant protégée par `anyio.CancelScope(shield=True)` et le test passe.
Cela supprime cette fuite de ressource ; les autres risques de disponibilité de SEC-03 demeurent.

## Protections vérifiées

| Domaine | Contrôles présents et examinés |
| --- | --- |
| Mots de passe | Argon2id, sels, vérification factice pour comptes absents, travail hors boucle événementielle et admission bornée ; paramètres minimums en production |
| Sessions | Jetons opaques aléatoires de 256 bits ; empreintes en base ; cookie hôte, HttpOnly, SameSite=Lax, Secure en production ; délais absolu/inactivité côté serveur |
| Révocation | Compte/session revérifiés en transaction ; révocation après changement/réinitialisation du mot de passe et archivage ; droits relus pour les opérations sensibles |
| Invitations | Jetons à usage unique, durée limitée, empreintes en base ; renouvellement révoquant les anciens ; liens utilisant un fragment ; aucun secret renvoyé dans les erreurs de formulaire |
| CSRF et BFF | Origine exacte ; en-tête personnalisé de l'API ; écritures du BFF validées avant ajout d'en-têtes de confiance ; cookie de session seul relayé ; destinations fixes et redirections refusées |
| Proxy | API/DB sans port public dans Compose principal ; frontend sur loopback ; adresses de proxy explicitement autorisées ; en-têtes entrants remplacés par le proxy prévu |
| Autorisations | Capacités explicites côté API ; profils enseignants bornés aux promotions partagées ; modifications de rôles réservées aux administrateurs ; aucun droit fondé seulement sur l'interface |
| Injections | Requêtes SQL paramétrées ; noms de colonnes choisis par le code ; contrats refusant les champs supplémentaires ; texte Svelte échappé ; aucune exécution de code déposé identifiée |
| Entrées HTTP | Petits corps JSON bornés avant parsing ; exceptions uniquement pour la route binaire exacte ; tailles déclarées et réelles vérifiées ; délais de lecture |
| Dépôt de fichiers | Éditeur courant requis, réservation personnelle à usage unique, quotas atomiques et plafond des réservations ; droits et version revérifiés après transfert/validation |
| Formats | Extensions et MIME serveur, structures images/PDF/Office/ZIP/Python vérifiées ; limites de complexité ; refus des chemins ZIP dangereux, symlinks, chiffrement et macros détectées |
| Stockage | Clés UUID générées, noms d'origine jamais utilisés comme chemins, répertoires privés hors racine web, contrôle des symlinks, publication par renommage sur le même volume |
| Téléchargement | Session active, cours et fichier associés, audiences/dates courantes ; pièce jointe avec nom Unicode encodé ; `no-store`, `nosniff`, `noindex` ; taille et SHA-256 avant envoi |
| Suppressions | File durable créée par déclencheur PostgreSQL, y compris cascades ; reprise des échecs ; rapprochement des orphelins après délai de grâce |
| Données publiques | API publique limitée à la présentation et au calendrier ; sitemap limité à l'accueil ; protections d'accès indépendantes de robots/noindex |
| Confidentialité des erreurs | Corps de validation, SQL, paramètres, secrets et diagnostics de parseurs non renvoyés aux clients par les gestionnaires examinés |

## Modifications et tests ajoutés

Suppression du client et des paramètres antivirus, du service/image/configuration Docker dédiés,
de son réseau et de sa déclaration de volume ; mise à jour du message de progression, du guide
documentaire et du README. Nettoyage des imports et des faux scanners des tests ; la validation
réelle reste exécutée. Aucun volume existant n'a été supprimé par cette suppression de configuration.

La suppression de ClamAV ne démarre ni n'arrête les services existants. Un ancien conteneur ou
volume de signatures peut donc encore exister dans une installation déjà lancée ; leur retrait
opérationnel éventuel est distinct. Ne pas utiliser `down --volumes` sur cette installation.

Tests de sécurité supplémentaires : fichier réel fermé malgré annulation, publication sans service
réseau, refus élève et autre enseignant sur une réservation étrangère, annulation étrangère sans
consommation de la réservation, origine hostile, réutilisation d'un dépôt, fichier d'un autre cours,
révocation de promotion, session absente, révocation de session/matière/compte pendant validation,
absence de publication après refus et concurrence des réservations de quota.

## Vérifications de l'incrément initial : retrait de l'antivirus

| Commande / vérification | Résultat |
| --- | --- |
| `python -m pytest -q`, depuis `backend/`, état final | 188 réussis, 122 intégrations ignorées sans base dédiée ; ces intégrations passent avec le lanceur Docker ci-dessous |
| `python -m pytest -q tests/test_document_storage.py`, après correction de l'annulation | 11 réussis ; le cas d'annulation avait d'abord échoué avant correction |
| `python run_tests.py --tb=short`, avec `BFF_INTEGRATION=1` et `BFF_BROWSER_INTEGRATION=1` | 304 réussis sur PostgreSQL jetable après retrait de l'antivirus ; parcours HTTP et navigateurs desktop/mobile réussis |
| `python run_tests.py --tb=short`, après correction et ajout de tous les cas de sécurité | 310 réussis sur PostgreSQL jetable, aucune intégration ignorée |
| `python -m ruff check .`, depuis `backend/`, état final du code | Réussi |
| `npm test`, depuis `frontend/` | 39 réussis |
| `npm run check` | 0 erreur, 0 avertissement |
| `npm run lint` | Réussi après formatage du message modifié |
| `npm run build` | Réussi ; avertissement de conflit `NO_COLOR`/`FORCE_COLOR` de l'environnement |
| `docker compose config --quiet` | Réussi |
| `docker compose -f compose.yaml -f compose.local.yaml config --quiet` | Réussi |
| Builds Docker via le lanceur existant | Images PostgreSQL/backend/migration construites ; frontend construit et utilisé pour les parcours BFF/navigateur |
| Dépendances | `npm audit` : 0 alerte ; 54 distributions Python examinées via PyPI, réserve Certifi décrite dans SEC-06 |

Les parcours navigateur ont précédé le seul correctif de fermeture du flux backend ; le code frontend
n'a ensuite pas changé. Le dernier passage PostgreSQL inclut le correctif et tous les nouveaux tests.
Les deux projets jetables ont été nettoyés par le lanceur : conteneurs, réseaux, images nommées et
volumes de test supprimés. Aucune donnée ou volume d'installation existante n'a été supprimé.
Aucune commande Git, modification de secret réel, mise à jour de paquet installé ou migration n'a
été effectuée. Les caches/outils préexistants sont conservés.

Non réalisés : tests de charge/DDoS, audit des paquets système des images, pentest du serveur réel,
validation TLS/HSTS, inspection des ACL/secrets réels, restauration de sauvegarde et recherche dans
l'historique Git. Les vérifications réussies ne prouvent pas l'absence de vulnérabilités inconnues.

## Vérifications de l'incrément suivant : file globale des téléchargements

Choix validé : plafond global configurable dans le `.env`, sans limite par compte et avec attente
des demandes supplémentaires. Le `.env` local et son modèle contiennent maintenant
`DOCUMENT_MAX_CONCURRENT_DOWNLOADS=16` ; la configuration Compose résolue transmet bien cette valeur.
Aucun autre paramètre ou secret local n'a été affiché ou modifié.

Les nouveaux tests couvrent FIFO et capacité 1/2 avec un même compte, annulation/déconnexion d'un
client en attente, libération après erreur, maintien du créneau jusqu'à la fin d'un envoi HTTP lent,
et révocation du compte pendant une attente sur la vraie API PostgreSQL. Le test du BFF vérifie
le maintien du signal d'annulation du navigateur pour les téléchargements.

| Vérification | Résultat |
| --- | --- |
| `python -m pytest -q` | 195 réussis, 124 intégrations ignorées sans base dédiée |
| `python run_tests.py --tb=short`, avec `BFF_INTEGRATION=1` et `BFF_BROWSER_INTEGRATION=1` | 319 réussis avec PostgreSQL ; parcours HTTP et navigateur desktop/mobile réussis |
| `python -m ruff check .` | Réussi |
| `npm test` | 39 réussis |
| `npm run check` | 0 erreur, 0 avertissement |
| `npm run lint` et `npm run build` | Réussis |
| Compose principal et overlay local, `config --quiet` | Réussis |
| `nginx -t` dans un conteneur temporaire avec le fragment inclus dans un serveur de test | Réussi |
| Builds des images backend, migration, PostgreSQL et frontend via le lanceur existant | Réussis |

Les services, réseaux, images nommées et volumes du projet de test ont été supprimés par le lanceur.
Le conteneur Nginx temporaire et l'image téléchargée uniquement pour cette vérification ont été
supprimés. Aucune migration, commande Git, suppression de donnée existante ou modification du
déploiement en cours n'a été effectuée. Le fragment Nginx fourni reste à appliquer sur le proxy réel.
