# Installer OpenGPX Trainer, pas à pas

*[English version](install.md)*

OpenGPX Trainer est une appli gratuite pour rouler sur home trainer : suivre n'importe quel
parcours GPX ou faire des séances d'entraînement. Elle s'affiche dans ton navigateur internet
(Chrome, Safari, Firefox…) mais tourne sur ton ordinateur, sans compte à créer.

L'installation se fait en **trois commandes** tapées dans un terminal. Pas de panique : il
suffit de les copier-coller.

## 1. Ouvrir un terminal

Un terminal est une fenêtre où l'on tape des commandes au lieu de cliquer.

* **Mac** : appuie sur **Cmd + Espace**, tape **Terminal**, puis **Entrée**.
* **Windows** : ouvre le menu Démarrer, tape **PowerShell**, clique sur **Windows
  PowerShell**.

Une fenêtre avec un peu de texte et un curseur qui clignote s'ouvre. C'est normal.

## 2. Installer uv (une seule fois)

uv est un petit outil qui installe l'appli et tout ce dont elle a besoin. Copie la ligne de
ton ordinateur, colle-la dans la fenêtre (clic droit → Coller, ou Cmd+V / Ctrl+V) et appuie
sur **Entrée**.

**Mac :**

```
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows :**

```
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Attends que le texte arrête de défiler, puis **ferme la fenêtre et rouvre-en une** (comme à
l'étape 1). Sinon l'étape suivante ne marche pas.

## 3. Installer l'appli (une seule fois)

Dans la nouvelle fenêtre, colle cette ligne (la même sur Mac et Windows) et appuie sur
**Entrée** :

```
uv tool install https://github.com/gbourgarel/opengpx-trainer/releases/download/v1.0.0/opengpx_trainer-1.0.0-py3-none-any.whl
```

Ça prend une minute. C'est fini quand tu vois `Installed 1 executable: opengpx-trainer`.

## 4. Lancer l'appli (à chaque séance)

Ouvre un terminal (ou PowerShell), tape ceci et appuie sur **Entrée** :

```
opengpx-trainer
```

L'appli s'ouvre dans ton navigateur. Sinon, va à l'adresse **http://127.0.0.1:8000**.

⚠️ **Ne ferme pas la fenêtre du terminal pendant que tu roules** : c'est elle qui fait
tourner l'appli. À la fin, clique dans cette fenêtre, appuie sur **Ctrl + C** (même sur Mac),
puis ferme-la.

## 5. Connecter le home trainer et les capteurs

1. Réveille tes capteurs : quelques coups de pédale, la ceinture cardio sur toi.
2. Dans l'appli, ouvre l'onglet **Profile**. Remplis au moins **Rider weight** (ton poids),
   **Bike weight** (le poids du vélo) et ta **FTP**.
3. Dans **Devices**, clique sur **Scan for devices**. Dans la liste, clique sur **Use as
   trainer** en face de ton home trainer, et de même **Use as power meter** (capteur de
   puissance) / **Use as heart rate** (cardio) si tu en as.
4. Clique sur **Save profile** en bas de la page.
5. Clique sur **Connect sensors** en haut de la page.

Si un capteur n'apparaît pas :

* **Ferme Zwift, Garmin Express, TrainerRoad**, etc. : un capteur ne parle souvent qu'à une
  seule appli à la fois.
* **Bluetooth sur Mac** : la première fois, autorise-le pour Terminal dans **Réglages Système
  → Confidentialité et sécurité → Bluetooth**, puis relance l'appli.
* **Clé ANT+ USB sur Windows** : il lui faut un pilote, installé une fois avec le petit
  programme **Zadig** (https://zadig.akeo.ie/). Branche la clé, ouvre Zadig, choisis la clé
  dans la liste (*ANT USBStick2* ou *ANT USB-m Stick*), sélectionne **WinUSB** et clique sur
  **Install Driver**. Garmin Express ne verra plus la clé ensuite. Sur Mac, la clé ANT+ marche
  telle quelle.

## 6. Rouler

* Onglet **Routes (GPX)** : **Import GPX** ajoute un parcours ; choisis-le et clique sur
  **Ride this route**.
* Onglet **Workouts (ERG)** : importe une séance (fichier .zwo, .erg ou .mrc), ou **Load
  planned from intervals.icu** si tu utilises intervals.icu ; puis **Ride (ERG)**.

La sortie démarre quand tu pédales. À la fin, elle est enregistrée en fichier FIT : dans
l'onglet **History**, le bouton **.fit** le télécharge, pour l'envoyer sur Strava, Garmin
Connect, etc.

## Mettre à jour

Refais l'étape 3 avec le lien du fichier `.whl` le plus récent de la
[page Releases](https://github.com/gbourgarel/opengpx-trainer/releases). Tes sorties et tes
réglages sont conservés.

## Windows

L'appli n'a pas encore été essayée sur un vrai PC Windows avec des capteurs. Si quelque chose
coince, dis-le dans une [issue](https://github.com/gbourgarel/opengpx-trainer/issues) : les
retours sont bienvenus.
