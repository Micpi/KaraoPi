**But**: Fournir aux agents Copilot des informations concrètes et actionnables
pour être immédiatement productifs dans ce dépôt PiKaraoke.

**Architecture**:
- **App principal**: `app.py` : application Flask exposant l'API web et les routes UI.
- **Logique métier / player**: `karaoke.py` : classe `Karaoke` qui gère la queue,
  le playback (via `ffmpeg`), la génération du QR code et la découverte des chansons.
- **Helpers plates-formes**: `lib/get_platform.py`, `lib/omxclient.py`, `lib/vlcclient.py`.
- **Résolution de fichiers**: `lib/file_resolver.py` : extraction ZIP, paire `.mp3`+`.cdg`.
- **UI**: `templates/` + `static/` (Bulma, JS). Les endpoints rendent ces templates.

**Flux de données essentiels**:
- Les chansons sont des fichiers présents dans `--download-path` (par défaut `~/pikaraoke-songs`).
- Le serveur (Flask) garde un objet global `k` (instance de `Karaoke`) : toute route
  appelle des méthodes sur `k` (enqueue, skip, download_video, etc.).
- Le stream vidéo/audio est servi par `ffmpeg` lancé par `karaoke.play_file()` ;
  `ffmpeg` écoute sur le port `--ffmpeg-port` (par défaut `5556`) et le client TV
  charge `http://<host>:<ffmpeg-port>/<stream_uid>`.

**Points critiques / patterns à respecter**:
- Global state: `k.queue`, `k.now_playing`, `k.available_songs` sont en mémoire.
  Les modifications concurrentes sont possibles (threads pour téléchargements
  et ffmpeg). Respecter le modèle existant plutôt que d'introduire locks
  sauf si vous corrigez un bug clairement lié à la concurrence.
- Nommage des fichiers téléchargés: `%(title)s---%(id)s.%(ext)s`. Le suffixe
  `---<youtube id>` est utilisé pour retrouver la piste par id.
- CDG support: `lib/file_resolver.py` extrait `.zip` contenant `.mp3` + `.cdg`,
  ou recherche le `.cdg` adjacent pour un `.mp3`.
- Plate-forme: utilisez `lib/get_platform.py` pour comportements spécifiques (Pi vs Windows).

**Commandes de développement & exécution (concrètes)**:
- Installer dépendances (Linux/macOS): `./setup.sh`.
- Installer dépendances (Windows): `setup-windows.bat`.
- Lancer localement avec yt-dlp explicite et dossier de chansons:
  `python app.py -y /path/to/yt-dlp -d /path/to/songs -p 5555 -f 5556`
- Mode headless (ne pas lancer le splash/player): `python app.py --hide-splash-screen`

**Dépendances externes / intégrations**:
- `ffmpeg` doit être présent (>= 6.0 recommandé). Il est utilisé pour transcodage
  et streaming dans `karaoke.play_file()`.
- `yt-dlp` (ou `yt-dlp.exe`) est appelé pour recherche/téléchargement.
- `psutil`, `flask`, `flask-babel`, `ffmpeg-python`, `qrcode`, `unidecode` sont
  utilisés côté serveur — voir `requirements.txt`.

**Guides rapides pour modifications courantes**:
- Ajouter une nouvelle route: suivre le style de `app.py` (retourne templates
  via `render_template` et utilise `flash()` pour messages UI).
- Changer le comportement de lecture/transcode: modifier `karaoke.play_file()`;
  attention à `self.ffmpeg_process` et à `kill_ffmpeg()` qui nettoient le process.
- Améliorer la recherche/queue: `karaoke.get_search_results()`, `enqueue()`.

**Où regarder pour exemples concrets**:
- `app.py` : usage intensif de l'objet global `k` et des routes exposées.
- `karaoke.py` : implémentation du run-loop, gestion des threads et ffmpeg.
- `lib/file_resolver.py` : règles exactes d'extraction/association `.mp3`+`.cdg`.
- `templates/*` et `static/*` : conventions CSS/JS (Bulma + custom JS) utilisées
  par le front-end.

**Ce que l'agent doit éviter/assumer**:
- Ne pas modifier la logique globale de queue pour éliminer la mémoire partagée
  sans d'abord proposer une migration (p.ex. vers un backend persistant).
- Éviter d'inventer endpoints publics — privilégier réutilisation des routes
  existantes (par ex. `enqueue`, `download`, `nowplaying`).

Si des sections sont peu claires (ex. emplacement exact de l'instanciation
de `k`, ou workflow de build sur Windows), dites-moi lesquelles et j'ajusterai
ce document avec exemples de commandes ou extraits de code supplémentaires.
