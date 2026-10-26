# Audit des ressources des cours interactifs

Document historique : l'implémentation ultérieure est décrite dans [les cours](lessons.md) et
[le guide documentaire](lesson-documents.md). Elle conserve la lecture globale des enseignants,
ajoute les khôlleurs collaborateurs aux espaces privés et utilise des titres de colonnes et noms
de documents libres. Les constats et propositions ci-dessous décrivent l'état avant ces ajouts.
L'antivirus proposé ci-dessous a depuis été retiré à la demande du mainteneur ; voir
[l'audit de sécurité actuel](security-audit.md) et le guide documentaire pour la politique applicable.

Audit du code et de la configuration du dépôt au 26 octobre 2026. Les propositions ci-dessous
restent à valider avant développement. Seule la suppression du libellé automatique « Section N »
est réalisée : le titre saisi est le premier texte du bloc, les ancres du sommaire sont conservées.

## 1. Existant vérifié

| Domaine | État actuel | Conséquence |
| --- | --- | --- |
| Page | `frontend/src/routes/lessons/[id]/+page.svelte`, lecture et édition séparées | Conserver la page et ses composants, ajouter des éditeurs spécialisés. |
| Contenu | `LessonContent.svelte` : sections, sous-sections, textes et liens YouTube | Aucun dépôt, téléchargement ni tableau de ressources. |
| Modèle | `backend/app/models/lessons.py` : `Lesson`, `LessonElement`, collaborateurs et promotions | IDs stables, ordre et parenté déjà réutilisables. |
| Hiérarchie | Sections à la racine ; sous-sections dans une section ; textes/vidéos dans les deux | Ajouter les ressources dans ces deux conteneurs. |
| Intégrité SQL | Migration `0005_lessons.py` : clés étrangères composites, cascades, contraintes et déclencheur de parenté | Une simple extension TypeScript ne suffira pas ; nouvelle migration nécessaire. |
| Dates | `effective_period()` dans `backend/app/services/lessons.py` | Héritage déjà calculé côté serveur, dates inclusives, calendrier Europe/Paris. |
| Confidentialité | Les feuilles indisponibles sont retirées des réponses élèves ; les titres structurels restent visibles | Appliquer aussi le filtrage aux fichiers, cellules et liens de téléchargement. |
| Lecture | Tous les enseignants et administrateurs lisent les cours ; les khôlleurs collaborateurs ont une lecture complète | Un « corrigé prof » n'est pas protégé par le seul accès au cours. |
| Écriture | Responsable/collaborateur enseignant éligible à la matière, ou administrateur ; droits revérifiés en transaction | Distinguer l'auteur historique du responsable actuel. |
| Concurrence | Verrou du cours, `expected_version`, erreur 409, journal transactionnel | Réutiliser à la finalisation d'un upload et pour toute modification de politique. |
| Suppression | Suppression d'un sous-arbre d'éléments ; cascades SQL existantes | Aucun traitement disque ; aucune route de suppression du cours complet. |
| Transport | BFF `frontend/src/lib/server/backend.ts` et `lessons.ts` : JSON, liste de commandes autorisées, délai 15 s | Prévoir des routes binaires dédiées, sans passer par la conversion JSON. |
| Limites | Nginx `16k`, adapter Node `BODY_SIZE_LIMIT=16384`, middleware API à 16384 octets par défaut | Les trois couches bloquent les fichiers usuels. Le réglage API existant est plafonné à 1 Mio. |
| Stockage | `compose.yaml` ne persiste que PostgreSQL ; aucun volume documentaire du backend | Un fichier dans la couche du conteneur ne répond pas au besoin de persistance. |
| Sécurité HTTP | Origine exacte, CSRF, session HttpOnly, `no-store`, `nosniff`, `noindex`, `Referrer-Policy: same-origin` | Conserver ces protections et traiter le cas particulier du lecteur YouTube. |

Sources locales complémentaires : `backend/app/schemas/lessons.py`, `backend/app/core/http.py`,
`backend/app/core/auth_config.py`, `backend/app/api/v1/lessons.py`, `frontend/src/hooks.server.ts`,
`infra/nginx.conf`, `backend/pyproject.toml`, `backend/tests/test_lessons*.py`, `frontend/tests/browser.mjs`.
Les noms des variables de `.env` et `.env.example` ont été examinés sans afficher leurs valeurs ;
aucune configuration documentaire n'y est définie. Aucun service déployé ni fichier persistant réel
n'a été inspecté : cet audit décrit le dépôt, pas une vérification de l'exploitation.

## 2. Comportement recommandé

Dans une section ou sous-section : bouton « Ajouter un document », sélection ou glisser-déposer,
nom affiché modifiable, règle de dates et audience. La sélection annonce les extensions et la taille
limite avant transfert ; le serveur fournit ces limites à l'interface pour éviter leur duplication.
Afficher progression, annulation, validation en cours, succès et erreurs avec possibilité de réessayer.
Un abandon ne doit créer aucun document publié vide.

Une ressource téléchargeable présente une icône de type, un titre, l'extension et la taille.
Le clic télécharge via une route authentifiée, avec `Content-Disposition: attachment` et nom sécurisé.
Réutiliser `Icon.svelte` et la dépendance Font Awesome déjà présente pour les pictogrammes PDF,
image, Word, Excel, archive et code ; ajouter une indication textuelle accessible, pas seulement une couleur.
Une prévisualisation d'image/PDF est une option ultérieure distincte du téléchargement demandé.

Formats proposés au lancement : `.jpg`, `.jpeg`, `.png`, `.pdf`, `.docx`, `.xlsx`, `.zip`, `.py`.
Les anciens `.doc` et `.xls` répondent aussi au terme Word/Excel, mais demandent une validation
différente ; décider explicitement de leur support. Refuser initialement SVG, HTML, exécutables,
documents chiffrés et formats Office avec macros (`.docm`, `.xlsm`). Un fichier `.py` est une pièce
jointe à télécharger : aucune exécution, importation ou installation serveur. Afficher éventuellement
son texte échappé dans une phase ultérieure, sans interprétation.

### Dates : conserver exactement la règle existante

- `inherit` : règle explicite du plus proche parent ; sans règle, aucune restriction de contenu.
- `from` : accès dès la date indiquée, incluse.
- `range` : accès entre deux dates incluses.
- Une règle explicite remplace celle du parent : elle ne s'intersecte pas avec elle.
- Exemple : section disponible en septembre ; document explicitement disponible en octobre :
  le document peut être ouvert en octobre, si l'utilisateur conserve l'accès au cours.
- L'accès par promotion reste un préalable indépendant : aucune date documentaire ne le rétablit.
- Une échéance masque l'accès ; elle ne supprime jamais le fichier disque.

Appliquer le même calcul aux ressources des tableaux. Un tableau peut porter une règle, héritée
par ses ressources, elles-mêmes configurables. Extraire une fonction de calcul commune plutôt
que réécrire une variante des dates. Vérifier les dates à chaque téléchargement, pas seulement
au chargement de la page : un onglet déjà ouvert peut dépasser l'échéance.

## 3. Base de données et intégrité

Conserver les octets sur disque et les métadonnées dans PostgreSQL. Il n'est pas nécessaire de
dupliquer le binaire en base : cela alourdirait sauvegardes et restaurations sans résoudre à lui
seul les validations de sécurité. Le schéma suivant est une proposition conceptuelle, pas un DDL approuvé.

| Entité | Informations et contraintes à prévoir |
| --- | --- |
| Élément de cours | Étendre les types pour une ressource documentaire et un tableau ; conserver parent, ordre, titre et dates. |
| Ressource | Propriétaire structurel : élément autonome ou cellule de tableau ; type fichier/YouTube, titre, audience et règle de dates. Un seul propriétaire, du même cours. |
| Fichier stocké | Identifiant opaque, clé relative unique, nom original borné, extension validée, MIME détecté, nombre d'octets, SHA-256, auteur du dépôt, dates et état de validation. Une ressource propriétaire unique au départ. |
| Colonne de tableau | Tableau propriétaire, clé stable, libellé, position ; unicité de la clé dans le tableau. |
| Cellule/ressource de colonne | Référence à la colonne, ordre si plusieurs fichiers ; dates et audience propres à chaque ressource. |
| Tâche de suppression | Clé disque, identifiant de tâche, état, essais et prochaine tentative ; persiste après suppression du cours propriétaire. |

Les vidéos existantes peuvent garder leur représentation actuelle au premier incrément. Éviter une
migration de leurs données sans nécessité ; partager leur validateur avec les vidéos des tableaux.
Pour le schéma final, ne pas conserver deux règles de dates contradictoires entre un élément
documentaire et sa ressource : choisir un propriétaire de référence par emplacement.

Contraintes : taille positive et bornée, SHA-256 au format attendu, clé de stockage unique,
références intra-cours, propriétaire exclusif, positions et audiences valides. Indexer les références
parentes et la file des tâches en attente. Ne pas dédupliquer les fichiers au premier incrément :
chaque dépôt a son fichier, ses droits et son cycle de vie. Un remplacement produit une nouvelle
clé immuable ; supprimer ensuite l'ancien fichier par le même mécanisme fiable.

Créer une nouvelle migration Alembic après la révision courante, sans modifier `0005_lessons`.
Adapter les contraintes `kind`/`content` et le déclencheur si la parenté change. Le service de
suppression actuel ne parcourt que deux niveaux descendants : si les tableaux ajoutent des
niveaux à `LessonElement`, remplacer cette hypothèse par un parcours complet/CTE récursive.
Une autre possibilité est de garder cellules et colonnes dans des tables dédiées, sans approfondir
l'arbre existant ; c'est le point de départ recommandé pour limiter les effets sur cet arbre.

### Ce que garantit l'empreinte

Calculer SHA-256 en lisant le flux serveur, compter les octets réellement reçus et stocker ces deux
valeurs. Une vérification périodique permet de repérer fichier absent, taille modifiée ou contenu
corrompu. Si une empreinte client est fournie, la comparer à celle calculée, sans lui faire confiance.
Une empreinte détecte une modification par rapport à la référence ; elle ne prouve ni l'absence
de virus ni l'authenticité d'un document. Si un attaquant peut modifier fichier et empreinte en base,
elle ne protège plus contre lui. Les fichiers validés doivent rester immuables et les écritures limitées.

## 4. Stockage permanent et réception fiable

Ajouter un volume nommé au `compose.yaml` existant, par exemple monté dans
`/var/lib/sophikron/documents` pour le backend et le processus de nettoyage. Variante : bind mount
vers un répertoire explicite de l'hôte, plus directement visible mais dépendant de ses chemins et
permissions. Préférer le volume nommé pour rester cohérent avec PostgreSQL. Les volumes Docker
survivent au remplacement du conteneur ; ils ne remplacent pas une sauvegarde.
Voir la [documentation Docker](https://docs.docker.com/engine/storage/volumes/).

Stocker sous des clés générées côté serveur, par exemple `ab/<uuid>`, jamais sous un chemin fourni
par l'utilisateur. Garder le nom d'origine en métadonnée uniquement. Répertoires privés, hors
webroot, pas de montage statique public, compte système à privilèges minimaux, pas d'exécution
de fichiers. Préparer les permissions pour l'UID 10001 utilisé par le backend.

Parcours proposé :

1. Vérifier session, droit de dépôt, parent et quota ; réserver une capacité sans garder une
   transaction/verrou du cours ouvert pendant tout le transfert.
2. Recevoir en flux dans un espace temporaire privé sur le même volume, compter les octets,
   calculer SHA-256 ; interrompre dès dépassement. Borner débit minimal/durée, concurrence et
   taille des champs de formulaire. Refuser les fichiers supplémentaires inattendus.
3. Valider contenu et antivirus ; garder le fichier inaccessible tant que la validation manque.
4. Déplacer atomiquement le fichier vers sa clé finale sur le même système de fichiers ; prévoir
   synchronisation disque appropriée si l'objectif inclut les coupures système.
5. Dans une transaction courte, revérifier les droits, l'existence du parent, le quota réservé et
   `expected_version`, puis publier métadonnées et journal. La suppression concurrente d'un parent,
   une révocation ou un conflit 409 doit empêcher la publication.
6. En cas d'échec, enlever le fichier non publié et libérer la réservation. Après un arrêt brutal,
   un rapprochement nettoie les temporaires et fichiers finaux non référencés, avec délai de grâce
   et protection des transferts actifs. Une clé d'idempotence évite les doublons après réponse perdue.

Base et disque ne partagent pas une transaction atomique : un `rollback` SQL n'annule pas une
écriture disque. Documenter et tester les reprises entre chaque étape. En cas d'analyse asynchrone,
persister aussi l'état d'upload et les tâches d'analyse pour survivre au redémarrage.

Sauvegarder ensemble la base et le volume avec une procédure cohérente, un manifeste de fichiers
et leurs empreintes ; tester la restauration sur un environnement séparé. Définir rétention,
capacité, alertes d'espace libre, sauvegardes hors machine et accès aux sauvegardes. Le stockage
local convient à un serveur ; plusieurs hôtes exigeraient un stockage partagé ou objet et une
nouvelle décision d'infrastructure. Ne pas ajouter ce service distant maintenant.

## 5. Suppression sans fichiers orphelins

Une cascade SQL ne supprime aucun octet sur disque. Une suppression avant le commit risque de
laisser un cours existant pointant sur un fichier perdu si la transaction échoue. Une suppression
après commit sans trace durable peut être oubliée lors d'un arrêt du processus.

Recommandation : une file transactionnelle de suppressions en PostgreSQL. Dans la même transaction
que la suppression de la ressource, enregistrer sa clé disque dans une tâche indépendante, puis
supprimer ses références et journaliser l'action. Le fichier devient immédiatement inaccessible
par l'application. Après commit, un traitement idempotent supprime le fichier ; une absence est
un succès, une erreur de disque déclenche une nouvelle tentative et une alerte après répétition.
Ne pas mettre de clé étrangère en cascade qui effacerait cette tâche avec le cours.

Pour couvrir aussi les cascades SQL, envisager un déclencheur de suppression sur les métadonnées
de fichiers, qui écrit les tâches avant leur disparition. Comparer cette option avec une collecte
explicite dans chaque service : le déclencheur couvre davantage de chemins de suppression,
le service reste plus simple à lire. Choisir une seule autorité et la tester sur PostgreSQL.
Un simple callback ORM ne couvre pas toutes les suppressions SQL en masse utilisées aujourd'hui.

Le traitement de reprise est nécessaire même si l'on tente une suppression immédiate après commit.
Définir un délai d'effacement disque observable, par exemple moins d'une minute en fonctionnement
normal, plutôt que promettre une simultanéité disque/base impossible en présence de panne.
Les clés ciblées restent confinées à la racine documentaire, sans suivre de liens symboliques.
Prévoir une commande de rapprochement d'abord en mode rapport ; ne jamais purger automatiquement
un volume entier. Une suppression dans le stockage actif n'efface pas instantanément les
sauvegardes : leur rétention doit être explicite et leur restauration doit rejouer les suppressions.

Ajouter également une vraie suppression de cours : route API, service autorisé, contrôle de version,
confirmation indiquant éléments/fichiers concernés, journal et redirection. Le droit de supprimer
tout un cours reste à trancher : responsable/administrateur recommandé, collaborateurs à discuter.

## 6. Sécurité et limites d'upload

Ne pas faire confiance au suffixe ni au `Content-Type` envoyé. Croiser extension autorisée,
type détecté et validation structurelle bornée ; ce sont plusieurs contrôles, pas une seule signature.
La [fiche OWASP sur les uploads](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)
souligne notamment les risques des archives et le stockage hors webroot.

- Images : décodage vérifié, limites de dimensions/pixels et ressources, pas seulement taille compressée.
- PDF : vérifier structure, refuser les documents chiffrés non analysables ; téléchargement en pièce jointe.
- DOCX/XLSX : vérifier les structures Office attendues dans le conteneur ZIP ; refuser macros et
  contenus interdits. Ne pas convertir ni lancer Office/LibreOffice sur le serveur à ce stade.
- ZIP : aucune extraction ou exécution applicative ; inspection/analyse sous limites de nombre
  d'entrées, taille décompressée et profondeur. Refuser chemins traversants/absolus, liens dangereux,
  chiffrement et archives qu'on ne peut analyser. Refuser les archives imbriquées au lancement.
- Python : texte de code téléchargeable, jamais exécuté ; le serveur ne peut certifier ce qu'il fera chez l'élève.
- Antivirus local en quarantaine : par exemple ClamAV, candidat à valider pour maintenance,
  licence, mémoire et coût d'exploitation. Signature indisponible/analyse interrompue : pas de publication.

Le contrôle de structure et l'antivirus réduisent les risques sans garantir l'innocuité de chaque
fichier. Pour éviter de divulguer des documents scolaires, ne pas envoyer les fichiers à un
scanner public externe. Les analyseurs doivent eux-mêmes être maintenus et limités en ressources.

Valeurs initiales proposées, à approuver et configurer en octets, avec 1 Mio = 1 048 576 octets :

| Type | Maximum proposé par fichier |
| --- | --- |
| JPEG/PNG | 10 Mio |
| PDF, Word, Excel | 25 Mio |
| ZIP | 50 Mio |
| Python | 1 Mio |

Ajouter un quota global, par cours et par déposant, un plafond de transferts simultanés et une
réserve d'espace disque. Leur valeur dépend de la capacité et des sauvegardes ; une limite par
fichier seule ne borne pas le stockage total. Réserver les quotas atomiquement pour éviter que
plusieurs transferts parallèles les dépassent.

Conserver les petits plafonds pour les routes JSON/authentification. Ajouter un budget dédié aux
routes d'upload, y compris marge multipart, au proxy, à Node et au middleware API ; ne pas lever
globalement la limite du middleware ni charger 50 Mio en mémoire via `chunks` puis `join`.
Le plafond Node est global : l'augmenter exige aussi des limites adaptées aux autres routes du BFF.
Fixer le plafond proxy légèrement au-dessus du corps multipart autorisé ; le quota fichier exact
reste vérifié en flux. Tester `Content-Length` absent et les transferts découpés.

Pour un PDF trop gros : bloquer localement avant l'envoi, annoncer la limite puis proposer le
lien [Compresser avec iLovePDF](https://www.ilovepdf.com/fr/compresser_pdf) dans un nouvel onglet.
Pas de redirection automatique ni de transmission du document par Sophikron. Indiquer que l'envoi
sur ce site tiers relève d'une démarche distincte, surtout pour les documents contenant des données
élèves. Proposer une compression locale pour ces documents ; ne pas rendre le tiers obligatoire.

Le backend ne déclare actuellement pas `python-multipart` ni de bibliothèque de validation
d'images/PDF. Une implémentation multipart avec `UploadFile` nécessitera une dépendance explicite ;
la mise en fichier temporaire fournie par FastAPI ne remplace pas les limites de flux en amont.
Voir [FastAPI : fichiers reçus](https://fastapi.tiangolo.com/tutorial/request-files/).
Choisir les analyseurs et leurs licences/maintenance avant ajout, sans installer de dépendance à ce stade.

## 7. Téléchargement et permissions par fichier

Chaque requête de téléchargement doit revérifier : session active, droit courant d'ouvrir le
cours, audience du fichier, dates effectives, état validé et existence du fichier. Vérifier aussi
l'association cours/élément/fichier ; un identifiant deviné ou un ancien lien ne suffit pas.
Un nom opaque ne remplace pas une autorisation. Les réponses de page et tableaux doivent déjà
retirer les ressources interdites, sans exposer leur nom, URL ou empreinte dans le HTML/hydratation.

Point de départ recommandé pour l'audience, à valider :

| Audience | Lecture proposée |
| --- | --- |
| Lecteurs du cours | Comptes actuellement autorisés à ouvrir le cours, avec dates appliquées aux élèves. |
| Équipe du cours | Responsable et collaborateurs enseignants éligibles ; administrateurs. Khôlleurs à décider. |
| Éditeurs/administrateurs | Gestion et contrôle des ressources selon les capacités courantes, sans droit fondé sur l'auteur historique. |

« Prof uniquement » est ambigu : tous les enseignants de l'établissement, ou seulement l'équipe
du cours ? Je recommande la seconde règle pour les corrigés sensibles. Elle restreint la lecture
globale actuelle des enseignants pour ces seules ressources. Décider aussi si l'équipe peut
télécharger hors dates comme elle lit déjà les textes non disponibles aux élèves.
L'audience est une barrière d'autorisation distincte des dates : une date élève ne doit jamais
rendre public un fichier réservé à l'équipe. Dans un tableau, les ressources héritent au minimum
de l'accès au cours ; éviter qu'un enfant élargisse silencieusement une audience parent restrictive.
Une règle simple est une intersection des audiences, même si les dates restent un remplacement.

Utiliser une route GET du BFF pour le téléchargement et transférer le flux binaire, sans JSON ni
chargement intégral en mémoire. Contrôler annulation et propagation des erreurs ; laisser `no-store`,
`nosniff`, `noindex`, un MIME choisi côté serveur et `Content-Disposition` sûr. Borner le nom affiché,
retirer séparateurs/contrôles et encoder correctement les noms Unicode. N'exposer aucun chemin disque.
Ne pas remettre une URL publique permanente ni un lien de stockage contournant les droits.
Le support de `HEAD`/`Range`, s'il est ajouté, doit appliquer exactement la même politique.
Un fichier déjà téléchargé ne peut plus être révoqué sur le poste de son destinataire.

## 8. YouTube intégré

Réutiliser le validateur existant : HTTPS, hôtes exacts, identifiant de 11 caractères, URL canonique,
aucun HTML iframe utilisateur ni récupération serveur d'URL arbitraire. Construire l'iframe depuis
l'identifiant validé. Pas de clé API requise pour ce simple lecteur.

Proposition : bouton « Charger la vidéo YouTube », puis lecteur responsive 16:9 dans le cours,
sans autoplay, avec titre accessible et lien externe de secours. Le chargement après clic évite
de contacter YouTube avant l'action ; une miniature distante ferait déjà ce contact, donc utiliser
un visuel local. Garder le filtrage API et les dates avant de livrer l'identifiant vidéo.

Utiliser `youtube-nocookie.com` pour le mode de confidentialité avancée ; cela ne signifie pas
absence de communication avec Google après chargement. Voir [l'aide officielle sur les lecteurs](https://support.google.com/youtube/answer/171780).
Le réglage global actuel `Referrer-Policy: same-origin` supprime le référent vers YouTube.
Prévoir `referrerpolicy="strict-origin-when-cross-origin"` sur cette seule iframe pour transmettre
l'origine du site, sans le chemin privé du cours ; vérifier dans un vrai navigateur.
Google demande ce référent et documente la politique recommandée dans les
[exigences minimales du lecteur](https://developers.google.com/youtube/terms/required-minimum-functionality).
Ne pas modifier globalement les protections de formulaire pour cette intégration.

Prévoir une éventuelle directive CSP `frame-src` autorisant le lecteur si une CSP est introduite.
`X-Frame-Options: DENY` sur Sophikron protège l'intégration de Sophikron ailleurs ; il n'empêche pas
à lui seul d'intégrer YouTube dans Sophikron. Vidéo retirée, privée ou intégration interdite :
message compréhensible et lien de secours. Sophikron ne garantit ni disponibilité ni confidentialité
d'une vidéo hébergée chez YouTube ; un lien non répertorié reste partageable hors plateforme.

## 9. Tableaux de ressources

Créer un type de bloc dédié « Tableau de ressources », dans une section ou sous-section,
avec une ligne de ressources et plusieurs colonnes configurables. Exemple de présentation :

| Sujet élève | Corrigé prof | Corrigé élève |
| --- | --- | --- |
| sujet.pdf — lecteurs du cours | notes.docx — équipe du cours | correction.pdf — lecteurs du cours, à partir d'une date |

Le nom de colonne est une présentation ; il ne donne aucun droit. Chaque ressource conserve son
audience et sa règle de dates, indépendamment des autres cellules. On peut ainsi proposer un
corrigé professeur permanent à l'équipe et une correction destinée aux élèves publiée plus tard.
Proposer des valeurs par défaut à la création, sans droits codés en dur d'après les libellés.

Édition : libellés, ordre des colonnes, ajout/remplacement/suppression de fichiers, avertissement
sur les ressources masquées et choix explicite de l'audience. Limiter le nombre de colonnes et
de fichiers pour garder un rendu et des requêtes bornés. Lecture : vrai tableau avec en-têtes,
navigation clavier, liens nommés ; sur mobile, présentation empilée répétant le nom de colonne.
Une cellule interdite est omise ou signalée génériquement selon le besoin validé, sans nom de fichier.

Deux sens possibles de « corrigé élève » changent fortement le périmètre :

- Document déposé par l'enseignant et destiné aux élèves : couvert par le modèle ci-dessus.
- Dépôt personnel de chaque élève : fonctionnalité de remise de travaux distincte, avec table de
  soumissions, identité propriétaire, sélection contrôlée des enseignants évaluateurs, calendrier
  de dépôt, remplacements/versions, quotas élèves et visibilité strictement séparée entre élèves.
  Les enseignants lecteurs globaux ne doivent pas automatiquement lire ces travaux personnels.

Ne pas ouvrir les routes d'upload aux élèves simplement parce qu'une colonne porte leur nom.

## 10. Composants touchés et vérification à prévoir

- Frontend : `LessonContent`, `ElementEditor`, `Icon`, types/commandes de cours ; nouveaux
  composants ciblés pour upload, carte fichier et tableau. Garder la logique métier dans l'API.
- BFF : routes upload/téléchargement dédiées, relais binaire borné, erreurs 401/403/409/413/422/503,
  maintien des cookies et contrôles d'origine ; délai de transfert distinct du JSON à 15 secondes.
- Backend : routes minces, service de ressources/droits, adaptateur disque, validation/analyse,
  dépôt SQLAlchemy, tâches durables de nettoyage ; réutiliser authentification et journal.
- Base : nouvelles tables/contraintes/index, extension des types d'éléments, migration réversible
  avec stratégie explicite pour les fichiers en cas de downgrade. Aucun reset de données.
- Infrastructure : volume, permissions, limites HTTP, espace temporaire, traitement de tâches et
  éventuel antivirus dans les fichiers Compose existants ; sauvegardes et supervision documentées.

Tests d'acceptation indispensables à l'implémentation :

1. Upload/téléchargement de chaque format, mauvais contenu sous bonne extension, fichier vide,
   taille exacte et dépassement, champs multipart excessifs, noms Unicode/chemins malveillants.
2. Limites appliquées avant et pendant transfert ; mémoire bornée ; annulation, timeout, disque plein,
   analyse refusée/indisponible, ZIP piégé/bombe et image aux dimensions excessives.
3. Élève autorisé ou extérieur au cours, élève différent pour les éventuelles remises personnelles,
   enseignant lecteur global, équipe, khôlleur, administrateur, compte désactivé et session révoquée.
4. Dates héritées à deux niveaux, remplacement explicite, bornes inclusives et minuit Paris,
   plusieurs promotions, révocation immédiate et téléchargement depuis un onglet ancien.
5. IDs appartenant à un autre cours, nom/URL d'un corrigé absent des réponses non autorisées,
   GET/HEAD/Range si disponibles, ancien lien après remplacement ou suppression.
6. Concurrence : parent supprimé pendant transfert, droits retirés, version périmée, quotas réservés
   en parallèle, requête réessayée ; aucun fichier publié ni quota bloqué après échec.
7. PostgreSQL réel : cascades élément/sous-section/section/cours et production atomique des tâches ;
   crash après commit, suppression disque échouée puis reprise, absence de fichier déjà supprimé.
8. Rapprochement, détection de corruption et restauration base+fichiers ; aucune purge de dépôt actif.
9. Parcours navigateur desktop/mobile, upload accessible, icônes/liens, dates/permissions par cellule,
   lecteur YouTube après clic, référent limité à l'origine et comportement de secours.

Exécuter alors pytest/Ruff, tests frontend/check/lint/build, intégration PostgreSQL et parcours
BFF/navigateur du projet, puis validation Compose/builds. Les tests existants couvrent déjà une
partie des droits, dates, conflits et références croisées, mais aucun cycle de vie de fichier.

## 11. Décisions et incréments proposés

Décisions avant développement :

1. « Corrigé élève » publié par l'enseignant ou remise personnelle de l'élève ?
2. Audience du corrigé prof : équipe du cours ou tous les enseignants ? Place des khôlleurs,
   accès hors dates et droits de suppression du cours complet ?
3. Support `.doc`/`.xls`, limites proposées, quota par cours/déposant et espace global disponible ?
4. Lecture YouTube après clic ou chargement automatique avec traitement explicite des implications ?
5. Exigence de délai de suppression disque, rétention des sauvegardes et moyen d'analyse antivirus ?

Ordre recommandé, avec revue entre incréments :

1. Valider politiques, stockage, dépendances et schéma ; formaliser les critères d'acceptation.
2. Livrer le cycle documentaire complet : validation, persistance, téléchargement autorisé,
   dates/audiences, remplacement, suppressions et reprise ; ne pas reporter le nettoyage après l'upload.
3. Ajouter le lecteur YouTube en conservant le validateur actuel.
4. Ajouter les tableaux à partir des mêmes ressources et politiques.
5. Si demandé, concevoir séparément les remises personnelles des élèves.

Vérifications de l'incrément livré avec cet audit : `npm.cmd test` (33 tests réussis),
`npm.cmd run check` (0 erreur/avertissement), `npm.cmd run lint` et `npm.cmd run build` réussis.
Un contrôle navigateur ciblé sur la page compilée, avec données fictives locales, confirme le titre
en tête et les liens de sommaire section/sous-section. Le parcours complet avec backend n'a pas
été lancé ; pytest/Ruff et les vérifications d'infrastructure ne l'ont pas été non plus, leurs
composants n'étant pas modifiés. Aucun mécanisme d'upload, aucune migration, aucun service externe
n'est ajouté par cet audit. Aucune commande Git exécutée.
