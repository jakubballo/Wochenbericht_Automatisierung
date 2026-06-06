"""
Wochenbericht Automatisierung
==============================
1. Liest die Wochennotiz-Mail vom iPhone (Gmail)
2. Filtert nur Einträge von Montag bis zum heutigen Samstag
3. Poliert Tätigkeiten mit Gemini KI auf
4. Erstellt eine schöne PDF mit Gesamtstunden + Stunden pro Baustelle
5. Speichert lokal + versendet per Gmail
"""

import os
import base64
import re
import json
from datetime import datetime, timedelta, date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
import pickle

# ─────────────────────────────────────────────
#  KONFIGURATION wird aus config.json geladen
# ─────────────────────────────────────────────
def config_laden():
    config_pfad = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    if not os.path.exists(config_pfad):
        print(f"❌ config.json nicht gefunden: {config_pfad}")
        exit(1)
    with open(config_pfad, 'r', encoding='utf-8') as f:
        return json.load(f)

CFG               = config_laden()
GEMINI_API_KEY    = CFG["ANTHROPIC_API_KEY"]
GMAIL_CREDENTIALS = CFG["GMAIL_CREDENTIALS"]
EMPFAENGER_MAIL   = CFG["EMPFAENGER_MAIL"]
ABSENDER_MAIL     = CFG["ABSENDER_MAIL"]
NOTIZ_BETREFF     = CFG["NOTIZ_BETREFF"]
SPEICHER_BASIS    = CFG["SPEICHER_BASIS"]
# ─────────────────────────────────────────────

import anthropic
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request


SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send'
]


# ══════════════════════════════════════════════
#  GMAIL
# ══════════════════════════════════════════════

def gmail_authentifizieren():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(GMAIL_CREDENTIALS, SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as f:
            pickle.dump(creds, f)
    return build('gmail', 'v1', credentials=creds)


def notiz_aus_mail_lesen(service):
    """Sucht die Wochennotiz-Mail von diesem Samstag (heute)"""
    heute = datetime.now()
    # Suche Mails der letzten 2 Tage mit dem Betreff
    ergebnis = service.users().messages().list(
        userId='me',
        q=f'subject:"{NOTIZ_BETREFF}" newer_than:2d'
    ).execute()

    nachrichten = ergebnis.get('messages', [])
    if not nachrichten:
        # Fallback: letzte 7 Tage
        ergebnis = service.users().messages().list(
            userId='me',
            q=f'subject:"{NOTIZ_BETREFF}" newer_than:7d'
        ).execute()
        nachrichten = ergebnis.get('messages', [])

    if not nachrichten:
        print("❌ Keine Wochennotiz-Mail gefunden!")
        return None, None

    # Neueste Mail nehmen
    msg = service.users().messages().get(
        userId='me', id=nachrichten[0]['id'], format='full'
    ).execute()

    # Sendedatum der Mail prüfen
    headers = msg['payload'].get('headers', [])
    mail_datum = None
    for h in headers:
        if h['name'] == 'Date':
            mail_datum = h['value']
            break

    # Text extrahieren
    def text_aus_payload(payload):
        if payload.get('mimeType') == 'text/plain':
            data = payload.get('body', {}).get('data', '')
            if data:
                return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
        for part in payload.get('parts', []):
            result = text_aus_payload(part)
            if result:
                return result
        return ""

    text = text_aus_payload(msg['payload'])
    print(f"✅ Notiz gefunden ({len(text)} Zeichen)")
    return text, mail_datum


# ══════════════════════════════════════════════
#  DATUM & STUNDEN PARSER
# ══════════════════════════════════════════════

def stunden_berechnen(stunden_str):
    """
    Erkennt verschiedene Formate:
    - '1,5h' oder '1.5h'
    - '8:00-12:00' oder '8:00 - 12:00'
    - '7:30-13:30'
    Gibt float zurück (z.B. 4.0)
    """
    stunden_str = stunden_str.strip()

    # Format: 1,5h oder 1.5h oder 2h
    match = re.match(r'^(\d+)[,.](\d+)h$', stunden_str, re.IGNORECASE)
    if match:
        return float(f"{match.group(1)}.{match.group(2)}")
    match = re.match(r'^(\d+)h$', stunden_str, re.IGNORECASE)
    if match:
        return float(match.group(1))

    # Format: 8:00-12:00 oder 8:00 - 12:00
    match = re.match(r'^(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})$', stunden_str)
    if match:
        start = int(match.group(1)) * 60 + int(match.group(2))
        ende  = int(match.group(3)) * 60 + int(match.group(4))
        return round((ende - start) / 60, 2)

    return 0.0


def datum_normalisieren(datum_str, aktuelles_jahr=None):
    """
    Erkennt: '01.06', '02.06', '03.06.26', '03.06.2026'
    Gibt datetime.date zurück
    """
    if aktuelles_jahr is None:
        aktuelles_jahr = datetime.now().year

    datum_str = datum_str.strip()

    # DD.MM.YY oder DD.MM.YYYY
    match = re.match(r'^(\d{1,2})\.(\d{1,2})\.(\d{2,4})$', datum_str)
    if match:
        tag, monat, jahr = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if jahr < 100:
            jahr += 2000
        return date(jahr, monat, tag)

    # DD.MM (kein Jahr)
    match = re.match(r'^(\d{1,2})\.(\d{1,2})$', datum_str)
    if match:
        tag, monat = int(match.group(1)), int(match.group(2))
        return date(aktuelles_jahr, monat, tag)

    return None


def woche_bestimmen():
    """Gibt Montag und Samstag der aktuellen Woche zurück"""
    heute = date.today()
    wochentag = heute.weekday()  # 0=Mo, 5=Sa, 6=So
    montag = heute - timedelta(days=wochentag)
    samstag = montag + timedelta(days=5)
    return montag, samstag


def mail_text_parsen(text):
    """
    Parst den Mail-Text in strukturierte Tageseinträge.
    Erkennt Muster wie:
      01.06 Grenzstrasse
      1,5h
      Tätigkeiten...

      02.06 Ruhrverband
      8:00-12:00
      Tätigkeiten...
    """
    montag, samstag = woche_bestimmen()
    aktuelles_jahr = date.today().year

    tage = []
    zeilen = text.strip().split('\n')
    zeilen = [z.strip() for z in zeilen if z.strip()]

    # "Von meinem iPhone gesendet" entfernen
    zeilen = [z for z in zeilen if 'iphone' not in z.lower() and 'gesendet' not in z.lower()]

    i = 0
    while i < len(zeilen):
        zeile = zeilen[i]

        # Datum-Zeile erkennen: beginnt mit DD.MM oder DD.MM.JJ
        datum_match = re.match(r'^(\d{1,2}\.\d{1,2}(?:\.\d{2,4})?)\s+(.*)', zeile)
        if datum_match:
            datum_str  = datum_match.group(1)
            baustelle  = datum_match.group(2).strip()
            datum_obj  = datum_normalisieren(datum_str, aktuelles_jahr)

            if datum_obj and montag <= datum_obj <= samstag:
                stunden_str   = ""
                taetigkeiten  = []
                i += 1

                while i < len(zeilen):
                    naechste = zeilen[i]

                    # Nächstes Datum → neuer Tag
                    if re.match(r'^(\d{1,2}\.\d{1,2}(?:\.\d{2,4})?)\s+', naechste):
                        break

                    # Stunden erkennen
                    if re.match(r'^\d+[,.]?\d*h$', naechste, re.IGNORECASE) or \
                       re.match(r'^\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2}$', naechste):
                        stunden_str = naechste
                        i += 1
                        continue

                    # Tätigkeit
                    taetigkeiten.append(naechste)
                    i += 1

                stunden = stunden_berechnen(stunden_str) if stunden_str else 0.0

                tage.append({
                    "datum":         datum_obj,
                    "datum_str":     datum_obj.strftime('%d.%m.%Y'),
                    "wochentag":     ["Montag","Dienstag","Mittwoch","Donnerstag","Freitag","Samstag"][datum_obj.weekday()],
                    "baustelle":     baustelle,
                    "stunden_roh":   stunden_str,
                    "stunden":       stunden,
                    "taetigkeiten":  [t for t in taetigkeiten if t],
                })
                continue
        i += 1

    print(f"✅ {len(tage)} Tage in der Woche gefunden")
    return tage, montag, samstag


# ══════════════════════════════════════════════
#  GEMINI KI
# ══════════════════════════════════════════════

def taetigkeiten_aufhuebschen(tage):
    """Claude AI formuliert alle Tätigkeiten professionell um"""
    client = anthropic.Anthropic(api_key=GEMINI_API_KEY)

    eingabe = []
    for tag in tage:
        eingabe.append({
            "index": tage.index(tag),
            "taetigkeiten": tag["taetigkeiten"]
        })

    prompt = """Du bist ein professioneller Schreibassistent fuer Handwerker-Wochenberichte.

Deine Aufgabe: Schreibe die Taetigkeiten VOLLSTAENDIG NEU - professionell, klar und in ganzen Saetzen.
Die Originaltexte sind kurze Stichworte oder hastig getippte Notizen. Mache daraus lesbare, professionelle Saetze.

Regeln:
- IMMER vollstaendige Saetze schreiben (niemals Stichworte lassen wie sie sind)
- Fachbegriffe korrekt ausschreiben (z.B. Cat7-Kabel, Tueroffner, Serverraum)
- Mehrere kurze Stichworte zu einem Satz zusammenfassen wenn sinnvoll
- Nichts erfinden was nicht im Original steht
- Antworte NUR mit JSON, kein Markdown, keine Erklaerung

Beispiele:
- "Kabel ziehen durch Bohrung machen" -> "Kabeldurchfuehrung durch Bohrung hergestellt und Kabel gezogen"
- "Jalousie Schalter Schlafzimmer und Taster fehlende noch austauschen" -> "Jalousie-Schalter im Schlafzimmer sowie fehlende Taster ausgetauscht"
- "Im serverraum u1 cat7 Jack anschliessen am Kabel" -> "Im Serverraum U1 den Cat7-Netzwerkanschluss am Kabel angeschlossen"

Format (NUR dieses JSON):
[
  {
    "index": 0,
    "taetigkeiten": ["Umgeschriebener Satz 1", "Umgeschriebener Satz 2"]
  }
]

Hier die Taetigkeiten:
""" + json.dumps(eingabe, ensure_ascii=False)

    try:
        antwort = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        rohtext = antwort.content[0].text.strip()
        rohtext = rohtext.replace("```json", "").replace("```", "").strip()
        ergebnis = json.loads(rohtext)

        for eintrag in ergebnis:
            idx = eintrag['index']
            if 0 <= idx < len(tage):
                tage[idx]['taetigkeiten'] = eintrag['taetigkeiten']

        print("✅ KI hat Taetigkeiten aufgehubscht")
    except Exception as e:
        print(f"⚠️  KI-Fehler: {e}")
        import traceback; traceback.print_exc()

    return tage


# ══════════════════════════════════════════════
#  STATISTIKEN
# ══════════════════════════════════════════════

def statistiken_berechnen(tage):
    """Berechnet Gesamtstunden und Stunden pro Baustelle"""
    gesamt = 0.0
    pro_baustelle = {}

    for tag in tage:
        h = tag['stunden']
        gesamt += h
        b = tag['baustelle']
        pro_baustelle[b] = pro_baustelle.get(b, 0.0) + h

    return gesamt, pro_baustelle


def stunden_formatieren(h):
    """4.5 → '4 Std 30 Min'"""
    if h <= 0:
        return "–"
    ganze = int(h)
    minuten = round((h - ganze) * 60)
    if minuten == 0:
        return f"{ganze} Std"
    return f"{ganze} Std {minuten} Min"


# ══════════════════════════════════════════════
#  PDF
# ══════════════════════════════════════════════

def pdf_erstellen(tage, montag, samstag, ausgabe_pfad):
    """Erstellt die professionelle Wochenbericht-PDF"""

    gesamt_stunden, pro_baustelle = statistiken_berechnen(tage)

    doc = SimpleDocTemplate(
        ausgabe_pfad, pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm,
        topMargin=2.5*cm, bottomMargin=2*cm
    )

    # Farben
    dunkelblau = colors.HexColor('#1a2f4e')
    akzent     = colors.HexColor('#2e6da4')
    hellblau   = colors.HexColor('#dbe8f4')
    grau       = colors.HexColor('#6b7280')
    dunkelgrau = colors.HexColor('#374151')
    gruen      = colors.HexColor('#166534')
    hellgruen  = colors.HexColor('#dcfce7')

    # Styles
    st_titel = ParagraphStyle('Titel',
        fontName='Helvetica-Bold', fontSize=22,
        textColor=dunkelblau, alignment=TA_CENTER,
        spaceBefore=6, spaceAfter=14)
    st_untertitel = ParagraphStyle('Untertitel',
        fontName='Helvetica', fontSize=11,
        textColor=grau, alignment=TA_CENTER,
        spaceBefore=0, spaceAfter=8)
    st_tag_header = ParagraphStyle('TagHeader',
        fontName='Helvetica-Bold', fontSize=11,
        textColor=colors.white)
    st_baustelle = ParagraphStyle('Baustelle',
        fontName='Helvetica-Bold', fontSize=10,
        textColor=akzent, spaceBefore=5, spaceAfter=2)
    st_stunden_tag = ParagraphStyle('StundenTag',
        fontName='Helvetica-Oblique', fontSize=9,
        textColor=grau, spaceAfter=4)
    st_punkt = ParagraphStyle('Punkt',
        fontName='Helvetica', fontSize=10,
        textColor=dunkelgrau, leftIndent=10,
        spaceBefore=2, spaceAfter=2)
    st_section = ParagraphStyle('Section',
        fontName='Helvetica-Bold', fontSize=12,
        textColor=dunkelblau, spaceBefore=8, spaceAfter=4)
    st_footer = ParagraphStyle('Footer',
        fontName='Helvetica', fontSize=8,
        textColor=grau, alignment=TA_CENTER)
    st_gesamt = ParagraphStyle('Gesamt',
        fontName='Helvetica-Bold', fontSize=11,
        textColor=gruen)

    inhalt = []

    # ── Titel ──
    kw = montag.strftime('%V')
    inhalt.append(Paragraph("Wochenbericht", st_titel))
    inhalt.append(Paragraph(
        f"KW {kw}  ·  {montag.strftime('%d.%m.%Y')} – {samstag.strftime('%d.%m.%Y')}",
        st_untertitel))
    inhalt.append(Spacer(1, 0.3*cm))
    inhalt.append(HRFlowable(width="100%", thickness=2, color=akzent))
    inhalt.append(Spacer(1, 0.5*cm))

    # ── Tage ──
    for tag in tage:
        # Blauer Header-Balken
        header_text = f"{tag['wochentag']}  ·  {tag['datum_str']}"
        header_tab = Table([[Paragraph(header_text, st_tag_header)]], colWidths=[17*cm])
        header_tab.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,-1), akzent),
            ('TOPPADDING',    (0,0), (-1,-1), 7),
            ('BOTTOMPADDING', (0,0), (-1,-1), 7),
            ('LEFTPADDING',   (0,0), (-1,-1), 12),
        ]))
        inhalt.append(header_tab)

        # Baustelle + Stunden
        inhalt.append(Paragraph(f"📍 {tag['baustelle']}", st_baustelle))
        if tag['stunden'] > 0:
            inhalt.append(Paragraph(
                f"🕐 {tag['stunden_roh']}  →  {stunden_formatieren(tag['stunden'])}",
                st_stunden_tag))

        # Tätigkeiten
        for t in tag['taetigkeiten']:
            inhalt.append(Paragraph(f"• {t}", st_punkt))

        inhalt.append(Spacer(1, 0.5*cm))

    # ── Stunden-Zusammenfassung ──
    inhalt.append(HRFlowable(width="100%", thickness=1.5, color=akzent))
    inhalt.append(Spacer(1, 0.3*cm))
    inhalt.append(Paragraph("Stundenübersicht", st_section))

    # Tabelle: Stunden pro Baustelle
    tabellen_daten = [["Baustelle", "Stunden"]]
    for baustelle, stunden in sorted(pro_baustelle.items()):
        tabellen_daten.append([baustelle, stunden_formatieren(stunden)])

    # Gesamtzeile
    tabellen_daten.append(["GESAMT", stunden_formatieren(gesamt_stunden)])

    col_breiten = [12*cm, 5*cm]
    stunden_tab = Table(tabellen_daten, colWidths=col_breiten)
    stunden_tab.setStyle(TableStyle([
        # Header
        ('BACKGROUND',   (0,0), (-1,0), dunkelblau),
        ('TEXTCOLOR',    (0,0), (-1,0), colors.white),
        ('FONTNAME',     (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',     (0,0), (-1,0), 10),
        ('TOPPADDING',   (0,0), (-1,0), 8),
        ('BOTTOMPADDING',(0,0), (-1,0), 8),
        ('LEFTPADDING',  (0,0), (-1,-1), 12),
        # Datenzeilen
        ('FONTNAME',     (0,1), (-1,-2), 'Helvetica'),
        ('FONTSIZE',     (0,1), (-1,-2), 10),
        ('TOPPADDING',   (0,1), (-1,-2), 6),
        ('BOTTOMPADDING',(0,1), (-1,-2), 6),
        ('ROWBACKGROUNDS', (0,1), (-1,-2), [colors.white, hellblau]),
        ('ALIGN',        (1,0), (1,-1), 'CENTER'),
        # Gesamtzeile
        ('BACKGROUND',   (0,-1), (-1,-1), hellgruen),
        ('TEXTCOLOR',    (0,-1), (-1,-1), gruen),
        ('FONTNAME',     (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('FONTSIZE',     (0,-1), (-1,-1), 11),
        ('TOPPADDING',   (0,-1), (-1,-1), 8),
        ('BOTTOMPADDING',(0,-1), (-1,-1), 8),
        ('LINEABOVE',    (0,-1), (-1,-1), 1.5, gruen),
        # Rahmen
        ('BOX',          (0,0), (-1,-1), 1, akzent),
        ('INNERGRID',    (0,0), (-1,-1), 0.5, hellblau),
    ]))
    inhalt.append(stunden_tab)

    # ── Footer ──
    inhalt.append(Spacer(1, 0.5*cm))
    inhalt.append(HRFlowable(width="100%", thickness=1, color=hellblau))
    inhalt.append(Spacer(1, 0.2*cm))
    erstellt_am = datetime.now().strftime('%d.%m.%Y um %H:%M Uhr')
    inhalt.append(Paragraph(
        f"Erstellt am {erstellt_am}  ·  Dieses Dokument wurde durch einen automatisierten Prozess erstellt. "
        f"Bei Fragen bitte kontaktieren: {ABSENDER_MAIL}",
        st_footer))

    doc.build(inhalt)
    print(f"✅ PDF gespeichert: {ausgabe_pfad}")


# ══════════════════════════════════════════════
#  GMAIL SENDEN
# ══════════════════════════════════════════════

def pdf_per_gmail_senden(service, pdf_pfad, montag, samstag):
    kw = montag.strftime('%V')
    betreff = f"Wochenbericht KW {kw} · {montag.strftime('%d.%m.')} – {samstag.strftime('%d.%m.%Y')}"

    nachricht = MIMEMultipart()
    nachricht['To']      = EMPFAENGER_MAIL
    nachricht['From']    = ABSENDER_MAIL
    nachricht['Cc']      = ABSENDER_MAIL
    nachricht['Subject'] = betreff

    nachricht.attach(MIMEText(
        f"Hallo,\n\nim Anhang findest du den Wochenbericht KW {kw}.\n\nViele Grüße",
        'plain'))

    with open(pdf_pfad, 'rb') as f:
        anhang = MIMEBase('application', 'octet-stream')
        anhang.set_payload(f.read())
    encoders.encode_base64(anhang)
    anhang.add_header('Content-Disposition',
        f'attachment; filename="{os.path.basename(pdf_pfad)}"')
    nachricht.attach(anhang)

    raw = base64.urlsafe_b64encode(nachricht.as_bytes()).decode()
    service.users().messages().send(userId='me', body={'raw': raw}).execute()
    print(f"✅ Mail gesendet an: {EMPFAENGER_MAIL}")


# ══════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════

def main():
    print("\n🚀 Wochenbericht Automatisierung gestartet")
    print("=" * 45)

    # Monatsordner bestimmen (z.B. "Juni", "Juli")
    MONATE_DE = {
        1:"Januar", 2:"Februar", 3:"März",    4:"April",
        5:"Mai",    6:"Juni",    7:"Juli",     8:"August",
        9:"September", 10:"Oktober", 11:"November", 12:"Dezember"
    }
    monatsordner = MONATE_DE[date.today().month]
    SPEICHER_ORDNER = os.path.join(SPEICHER_BASIS, monatsordner)
    Path(SPEICHER_ORDNER).mkdir(parents=True, exist_ok=True)

    print("\n📧 Gmail verbinden...")
    service = gmail_authentifizieren()

    print("\n📨 Wochennotiz-Mail suchen...")
    rohtext, mail_datum = notiz_aus_mail_lesen(service)
    if not rohtext:
        return

    print("\n📅 Mail parsen (Montag–Samstag dieser Woche)...")
    tage, montag, samstag = mail_text_parsen(rohtext)

    if not tage:
        print("❌ Keine Einträge für diese Woche gefunden!")
        print("   Prüfe ob die Daten in der Notiz stimmen.")
        return

    print(f"\n🤖 KI formuliert Tätigkeiten um...")
    tage = taetigkeiten_aufhuebschen(tage)

    print("\n📄 PDF wird erstellt...")
    von_str = montag.strftime('%d.%m.%Y')
    bis_str = samstag.strftime('%d.%m.%Y')
    dateiname = f"Wochenbericht {von_str} - {bis_str}.pdf"
    pdf_pfad = os.path.join(SPEICHER_ORDNER, dateiname)
    pdf_erstellen(tage, montag, samstag, pdf_pfad)

    print("\n✉️  Mail wird versendet...")
    pdf_per_gmail_senden(service, pdf_pfad, montag, samstag)

    gesamt, pro_baustelle = statistiken_berechnen(tage)
    print(f"\n📊 Zusammenfassung:")
    print(f"   Gesamtstunden: {stunden_formatieren(gesamt)}")
    for b, h in sorted(pro_baustelle.items()):
        print(f"   {b}: {stunden_formatieren(h)}")

    print(f"\n✅ Fertig! PDF gespeichert: {pdf_pfad}")


if __name__ == "__main__":
    main()
