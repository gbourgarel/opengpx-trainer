# Utiliser OpenGPX Trainer

Ce guide te fait faire la première configuration, dans l'ordre, puis tes premières sorties. Pas
encore installé ? Voir le [guide d'installation](https://github.com/gbourgarel/opengpx-trainer/blob/main/docs/install.fr.md).

L'interface de l'appli est en anglais : les noms des boutons sont donnés tels qu'ils
apparaissent.

## Première configuration

Fais ces étapes une fois, dans cet ordre. Elles sont toutes dans l'onglet **Profile**, et rien
n'est pris en compte avant d'avoir cliqué sur **Save profile** (en bas de la page).

### 1. Cycliste et vélo (Rider & bike)

Remplis **Rider weight** (ton poids), **Bike weight** (celui du vélo) et ta **FTP** (la
puissance que tu tiens environ une heure ; une estimation suffit pour commencer). Les cibles
des séances et la puissance en Slope ERG sont des pourcentages de ta FTP, et la vitesse
virtuelle dépend des poids.

Facultatif : **Threshold HR** (fréquence cardiaque au seuil) colore ton cardio par zone pendant
la sortie.

### 2. Modèle de vitesse (Speed model)

Choisis le **Bike & position** qui correspond au tien (vélo de route mains en haut, en bas du
cintre, CLM…). Il règle la vitesse du vélo virtuel pour une puissance donnée. La ligne en
dessous donne des exemples (200 W sur le plat → … km/h).

### 3. Capteurs (Devices)

1. Réveille les capteurs : quelques coups de pédale, la ceinture cardio sur toi.
2. Ferme les autres applis qui pourraient les utiliser (Zwift, Garmin Express, TrainerRoad…) :
   un capteur n'accepte souvent qu'une connexion.
3. Clique sur **Scan for devices** (environ 6 s). La liste montre les capteurs ANT+ et
   Bluetooth.
4. Clique sur **Use as trainer** en face de ton home trainer, puis **Use as power meter**
   (capteur de puissance) et **Use as heart rate** (cardio) si tu en as. Le home trainer seul
   suffit : il mesure la puissance.
5. Clique sur **Save profile**.
6. Clique sur **Connect sensors** en haut de la page. Les points à côté de *Trainer*, *Power*
   et *HR* passent au vert quand chaque capteur est connecté.

La fois suivante, l'appli se connecte aux mêmes capteurs : seul **Connect sensors** est
nécessaire.

### 4. Source de puissance (Power source)

Avec un capteur de puissance sur le vélo, garde **Auto** : sa puissance sert pour la vitesse et
l'enregistrement, sinon c'est celle du home trainer. **Power match** corrige le home trainer
pour que le capteur de puissance affiche la puissance cible.

### 5. intervals.icu (facultatif)

Pour récupérer les séances prévues dans [intervals.icu](https://intervals.icu) et y envoyer tes
sorties : ton **Athlete ID** et ta **API key**, tous deux dans intervals.icu sous *Settings →
Developer settings*.

### 6. Calibration (si le home trainer la demande)

Certains home trainers veulent un **spin-down** après un échauffement. Quand le home trainer le
demande, l'onglet Ride l'indique avant la sortie ; on peut aussi le faire depuis Profile →
Devices, ou sortie en pause. Une fenêtre te guide : pédale jusqu'à la vitesse indiquée, puis
arrête de pédaler et laisse la roue ralentir seule. Un capteur de puissance peut de même faire
son **zéro** (zero offset) : pieds déclipsés, manivelles immobiles.

## Rouler sur un parcours (GPX)

1. Onglet **Routes (GPX)** : **Import GPX** (ou glisse des fichiers `.gpx` sur la page). Pour
   essayer, une [montée d'exemple](https://github.com/gbourgarel/opengpx-trainer/raw/main/samples/sample_climb.gpx).
2. Choisis le parcours. Avant de partir, tu peux régler :
   * le **vent** et l'**air** (température, humidité), ou **Weather now** pour la météo
     actuelle le long du parcours ;
   * **Reverse**, pour le faire dans l'autre sens ;
   * un départ en cours de route : clique sur la carte ou sur le profil d'altitude ;
   * une séance à suivre sur le parcours (**Workout** : elle fixe la cible pendant que le
     parcours tourne en boucle).
3. Clique sur **Ride this route** (**Ride with workout**), puis pédale : la sortie démarre
   toute seule.

Sur un parcours, ce qui pilote le home trainer se choisit dans les commandes de la sortie :

* **Slope ERG** (par défaut) : le home trainer tient une puissance cible qui suit la pente à
  venir (plus dans les montées, moins en descente), d'après ta FTP. Pas besoin de changer de
  vitesse. La courbe est dans Profile → *Slope ERG* ; **Effort** (↑ / ↓) l'augmente ou la
  baisse pendant la sortie.
* **Sim** : le mode classique. Le home trainer simule la pente (× le **trainer effect**, 50 %
  pour commencer), tu changes de vitesse et choisis ta puissance comme sur la route.
* **Manual** : une cible en watts que tu règles toi-même.

## Faire une séance (ERG)

1. Onglet **Workouts (ERG)** : **Import .zwo / .erg / .mrc** (ou glisse le fichier sur la
   page), ou **Load planned from intervals.icu**. Pour essayer, une
   [séance sweet spot](https://github.com/gbourgarel/opengpx-trainer/raw/main/samples/sweet_spot.zwo).
2. Clique sur **Ride (ERG)** et pédale. Le home trainer tient la puissance de chaque étape :
   pédale à la cadence que tu veux, pas besoin de changer de vitesse.

Pendant la séance : **Intensity** (↑ / ↓) ajuste toutes les cibles, **+1 min** allonge l'étape
en cours, **Skip step** passe à la suivante. Des bips 3-2-1 annoncent chaque changement d'étape
(**Sound on / off**, ou M).

## Pendant la sortie

* La sortie **se met en pause toute seule** quand tu arrêtes de pédaler et repart quand tu
  pédales.
* Clavier : **Espace** pause / reprise, **↑ / ↓** (ou + / −) la valeur de ce qui fixe la cible
  (intensité, effort ou watts), **M** le son, **V** la vue 3D immersive d'un parcours (**F**
  plein écran dedans, **Échap** pour en sortir).
* L'écran reste allumé pendant la sortie.
* Un bandeau rouge prévient quand un capteur n'envoie plus rien.

## Après la sortie

1. Clique sur **Stop**, puis **Save** (ou **Discard** pour l'effacer). Une sortie sur un
   parcours s'arrête toute seule à l'arrivée.
2. **How was it?** : ton ressenti, et si tu veux ce que tu as mangé et bu. C'est écrit dans le
   fichier FIT ; **Skip** pour passer.
3. Si intervals.icu est configuré, l'appli propose d'y envoyer la sortie (jamais sans
   demander).
4. Onglet **History** : toutes les sorties, avec le bouton **.fit** pour télécharger le
   fichier et l'envoyer sur Strava, Garmin Connect, etc.

## En cas de souci

* **Un capteur n'est pas trouvé** : réveille-le, ferme les autres applis, relance le scan. Sur
  Mac, le Bluetooth doit être autorisé pour Terminal (Réglages Système → Confidentialité et
  sécurité → Bluetooth). Sur Windows, une clé ANT+ a besoin du pilote WinUSB (voir le guide
  d'installation).
* **La page affiche « backend offline »** : la fenêtre du terminal qui fait tourner l'appli a
  été fermée ou arrêtée ; relance `opengpx-trainer`.
* **L'appli ou l'ordinateur a planté pendant une sortie** : la sortie est sauvegardée toutes
  les 30 s et réapparaît dans History au démarrage suivant.
* **La vitesse virtuelle semble trop rapide ou trop lente** : vérifie les poids et le Bike &
  position dans Profile.
