# Presence - detection de personnes par webcam

Prototype web qui detecte la classe `person` en direct depuis une webcam avec YOLOv8n et ONNX Runtime Web. Le flux et l'inference restent dans le navigateur : aucune video n'est envoyee a un serveur.

## Prerequis

- Node.js 20.19+ ou 22.12+ et npm.
- Un navigateur recent avec WebRTC et WebAssembly, ainsi qu'une webcam integree ou USB.
- Le modele YOLOv8n ONNX est fourni localement dans `public/models/yolov8n.onnx` (environ 12.2 MiB). ONNX Runtime Web est telecharge avec `npm install`.

## Lancer sur le PC

Depuis la racine du projet :

```powershell
npm install
npm run dev
```

Ouvrir l'adresse locale affichee par Vite, normalement `http://localhost:5173`. Cliquer sur **Demarrer la camera** et autoriser l'acces a la webcam. La detection fonctionne egalement avec `npm run build` puis `npm run preview`.

Choisir une source si plusieurs cameras sont disponibles, ajuster le seuil de confiance et regler la frequence selon la puissance de la machine. `YOLOv8n` est la variante nano de YOLOv8, communement choisie quand on demande un modele tiny/leger. Le modele detecte les classes COCO et l'application ne conserve que `person` (classe 0). L'inference ONNX est executee localement dans le navigateur via WebAssembly; la premiere initialisation peut prendre quelques secondes.

Le fichier ONNX provient du depot `salim4n/yolov8n-detect-onnx` sur Hugging Face. Ce depot ne declare pas de licence de poids dans ses metadonnees. Ultralytics publie son implementation sous AGPL-3.0 et propose une licence Enterprise pour certains usages. Confirmer les droits applicables au modele et a son usage avec l'equipe avant toute distribution ou exploitation commerciale.

## Alarme de presence

Le mode initial est `surveillance`. Une detection `person` avec une confiance strictement superieure a 75 % declenche une notification navigateur avec une capture recadree de la personne, puis des rappels toutes les 15 secondes tant qu'une personne reste detectee. Apres deux minutes sans neutralisation, une notification d'escalade est envoyee avec la derniere capture disponible. Les notifications navigateur necessitent l'autorisation demandee au demarrage de la camera. Le bandeau et la capture restent aussi visibles dans la page.

Le mode peut etre bascule avec le champ **Code de changement de mode**. Le code de demonstration est `0000` ; le modifier dans `MODE_ACCESS_CODE` dans `src/main.ts`. Chaque saisie valide bascule entre `surveillance` et `neutral`. Le champ du code est masque pendant l'analyse video et redevient visible apres l'arret. L'API JavaScript utilise le meme code :

```js
window.presenceAlarm.switchMode('0000')
window.presenceAlarm.getMode() // 'neutral' ou 'surveillance'
```

Passer en `neutral` annule les rappels et l'escalade en attente : la personne detectee est alors consideree comme autorisee. Ce PIN est dans le code client et protege seulement l'interface ; il ne constitue pas un controle d'acces securise. Pour une vraie protection, la validation du code doit etre faite par un serveur. Les alertes restent locales au navigateur ; aucun message ni capture n'est envoye vers un serveur ou un telephone.

## Essai sur Raspberry Pi

Le navigateur execute le modele, pas Node.js : installer Node pour lancer le serveur de developpement ou compiler, puis ouvrir l'application dans Chromium sur le Pi avec une webcam USB. Commencer en 640 x 480 avec **Economie CPU** (environ 0,8 analyse/s). Une resolution et une cadence plus elevees peuvent reduire la fluidite sur un Pi peu puissant.

Pour tester depuis un autre appareil du reseau, le navigateur exige HTTPS pour autoriser la camera. `localhost` est une exception securisee uniquement sur l'appareil qui ouvre la page. Pour un deploiement, servir le build sur une origine HTTPS, et verifier les performances sur le modele precis de Raspberry Pi cible.

Le fichier de poids est servi depuis l'application (`/models/yolov8n.onnx`); apres installation initiale des dependances, l'inference ne requiert pas de telecharger le modele depuis TensorFlow Hub.

## Limites

- YOLOv8n detecte des personnes dans une image ; il ne reconnait pas leur identite et ne suit pas leur trajectoire.
- Les performances et la precision varient selon la camera, la lumiere, la distance et la puissance du processeur.
- Le navigateur demande une autorisation camera. La webcam est arretee quand on clique sur le bouton d'arret ou quitte la page.

## Scripts

- `npm run dev` : serveur de developpement Vite.
- `npm run build` : verification TypeScript et build de production.
- `npm run preview` : servir localement le build de production.

## Simulateur Edge Sentinel-X

Le simulateur C++ de l'ESP8266 est isole dans [`edge-simulator/`](edge-simulator/README.md). Les alertes sont publiees uniquement lors d'un franchissement de seuil, d'une detection PIR ou d'un retour a la normale. Les limites par defaut sont humidite 40–60 %, temperature 35 °C et gaz 0.50; elles sont configurables dans `.env`. Les messages MQTT donnent le capteur, la valeur, la limite et une explication lisible. Le contrat complet est documente dans [`docs/mqtt.md`](docs/mqtt.md).