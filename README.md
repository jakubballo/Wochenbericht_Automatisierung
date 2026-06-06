# 📋 Wochenbericht Automatisierung

Automatische Erstellung und Versendung von wöchentlichen Arbeitsberichten als PDF.

## 🔄 Wie es funktioniert

```
iPhone (Samstag automatisch)
  └── iOS Shortcut liest Apple Notiz der Woche
  └── Sendet Inhalt per Mail an Gmail

PC (wenn er läuft)
  └── Python-Skript liest die Mail
  └── Claude AI formuliert Tätigkeiten professionell um
  └── Erstellt eine PDF mit Stundenübersicht
  └── Speichert PDF im Monatsordner
  └── Versendet PDF per Gmail
```

## ✨ Features

- 📅 Erkennt automatisch Montag–Samstag der aktuellen Woche
- 🤖 Claude AI schreibt hastige Notizen in professionelle Sätze um
- 🕐 Berechnet Arbeitsstunden pro Tag und pro Baustelle
- 📊 Stundenübersicht am Ende der PDF
- 📁 Speichert PDF automatisch im richtigen Monatsordner
- 📧 Versendet PDF automatisch per Gmail

## 🛠️ Installation

### 1. Python installieren
Lade Python von [python.org](https://python.org/downloads) herunter.
Wichtig: Haken bei **"Add python.exe to PATH"** setzen!

### 2. Abhängigkeiten installieren
```bash
pip install -r requirements.txt
```

### 3. Konfiguration einrichten
```bash
cp config.example.json config.json
```
Öffne `config.json` und trage deine Daten ein:

| Feld | Beschreibung |
|------|-------------|
| `ANTHROPIC_API_KEY` | API Key von [console.anthropic.com](https://console.anthropic.com) |
| `GMAIL_CREDENTIALS` | Pfad zur Google OAuth credentials.json |
| `EMPFAENGER_MAIL` | E-Mail-Adresse des Empfängers |
| `ABSENDER_MAIL` | Deine Gmail-Adresse |
| `NOTIZ_BETREFF` | Betreff den der iOS Shortcut verwendet |
| `SPEICHER_BASIS` | Basisordner wo die Monatsordner liegen |

### 4. Gmail API einrichten
1. Gehe zu [console.cloud.google.com](https://console.cloud.google.com)
2. Neues Projekt erstellen → Gmail API aktivieren
3. OAuth-Client (Desktop-App) erstellen
4. `credentials.json` herunterladen und in den Projektordner legen

### 5. Anthropic API Key
1. Registriere dich auf [console.anthropic.com](https://console.anthropic.com)
2. Erstelle einen API Key
3. Trage ihn in `config.json` ein

## 📱 iOS Shortcut einrichten

1. **Shortcuts-App** öffnen → **+** → Neue Automatisierung
2. Aktionen hinzufügen:
   - `Datum formatieren` → Format: `MMMM` (gibt aktuellen Monatsnamen aus)
   - `Notizen durchsuchen` → Suchbegriff: Variable *Monatsname*
   - `Mail senden` → An: deine Gmail, Betreff: `Wochennotiz`, Inhalt: Notiz
3. Automatisierung: Jeden **Samstag** um **08:00 Uhr**

## 📝 Format der Notiz

```
01.06 Grenzstrasse
1,5h
Jalousie Schalter austauschen

02.06 Ruhrverband
8:00-12:00
Kabel Kanal montieren
Kabel anschließen
```

Unterstützte Stundenformate:
- `1,5h` oder `2h`
- `8:00-12:00` (Von-Bis Uhrzeit)

## ⚙️ Automatisch ausführen (Windows)

1. `Windows + R` → `taskschd.msc`
2. Neue Aufgabe → Trigger: **Samstag, 10:00 Uhr**
3. Aktion: `python C:\Pfad\zu\wochenbericht.py`

## 📄 Beispiel-Output

Die generierte PDF enthält:
- Kopfzeile mit KW und Datum
- Pro Tag: Datum, Baustelle, Stunden, Tätigkeiten (KI-aufgehübscht)
- Stundenübersicht: Stunden pro Baustelle + Gesamtstunden

## 🔒 Sicherheit

`config.json`, `credentials.json` und `token.pickle` sind in `.gitignore` eingetragen
und werden **niemals** auf GitHub hochgeladen.

## 📦 Benötigte Pakete

Siehe `requirements.txt`:
- `anthropic` — Claude AI API
- `reportlab` — PDF-Erstellung
- `google-auth-oauthlib` — Gmail OAuth
- `google-api-python-client` — Gmail API
