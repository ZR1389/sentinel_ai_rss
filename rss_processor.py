import os
import redis

REDIS_URL = os.getenv("REDIS_URL")
redis_client = redis.Redis.from_url(REDIS_URL)

import re
import time
import json
import httpx
import feedparser
from datetime import datetime
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from hashlib import sha256
from pathlib import Path
from unidecode import unidecode
import difflib
from langdetect import detect
import requests
from googletrans import Translator
from feeds_catalog import LOCAL_FEEDS, COUNTRY_FEEDS, GLOBAL_FEEDS

with open('fcdo_country_feeds.json', 'r', encoding='utf-8') as f:
    FCDO_FEEDS = json.load(f)

load_dotenv()

from telegram_scraper import scrape_telegram_messages
from xai_client import grok_chat
from openai import OpenAI
from threat_scorer import assess_threat_level
from prompts import SYSTEM_PROMPT, TYPE_PROMPT, FALLBACK_PROMPT, SECURITY_SUMMARIZE_PROMPT

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

THREAT_KEYWORDS = [
    "assassination", "murder", "homicide", "killing", "slaughter", "massacre", 
    "mass shooting", "active shooter", "gunfire",
    "kidnapping", "abduction", "hijacking", "hostage situation", 
    "human trafficking", "sex trafficking", "rape", "sexual assault", "violent crime",
    "bombing", "improvised explosive device", "IED", "terrorist attack", "terrorism", 
    "suicide bombing", "drone attack", "explosion", "road ambush",
    "military coup", "military raid", "coup d'etat", "regime change", "military takeover", 
    "state of emergency", "martial law", "curfew", "roadblock", "police raid",
    "civil unrest", "riot", "protest", "political unrest", "uprising", "insurrection",
    "political turmoil", "political crisis", "demonstration", 
    "border closure", "flight cancellation", "airport closure", "lockdown",
    "embassy alert", "travel advisory", "travel ban", "security alert",
    "emergency situation", "evacuation", "government crisis", "war", "armed conflict",
    "pandemic", "viral outbreak", "disease spread", "contamination", "quarantine",
    "public health emergency", "infectious disease", "epidemic", "biological threat", "health alert",
    "data breach", "ransomware", "cyberattack", "hacktivism", "deepfake", "phishing",
    "malware", "cyber espionage", "identity theft", "network breach", "online scam",
    "digital kidnapping", "virtual kidnapping", "cyber kidnapping", "honey trap", "hacking attack",
    "cyber fraud", "crypto fraud", "financial scam", "organized crime",  
    "travel scam", "armed robbery", "assault on a foreigner", "assault on a tourist",
    "extremist activity", "radicalization", "jihadist", "pirate attack",
    "extremism", "armed groups", "militia attacks", "armed militants", "separatists",
    "natural disaster", "earthquake", "tsunami", "tornado", "hurricane", "flood", "wild fire",
    "police brutality", "brutal attack", "false imprisonment", "blackmail", "extortion"
]

KEYWORD_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(k) for k in THREAT_KEYWORDS) + r')\b',
    re.IGNORECASE
)

# --- Multilingual Keyword Map (expand as needed) ---
TRANSLATED_KEYWORDS = {
    "assassination": {
        "en": ["assassination", "murder", "homicide", "killing", "slaughter", "massacre", "mass shooting", "active shooter", "gunfire"],
        "es": ["asesinato", "matar", "homicidio", "matanza", "masacre", "tiroteo masivo", "asesinato en masa", "tirador activo", "tiradora activa", "tiroteo"],
        "fr": ["assassinat", "meurtre", "homicide", "massacre", "fusillade de masse", "massacre de masse", "tireur actif", "fusillade"],
        "zh": ["暗殺", "謀殺", "殺人", "殺害", "屠殺", "大屠殺", "大規模槍擊", "大規模殺戮", "活躍槍手"],
        "ru": ["убийство", "умерщвление", "бойня", "резня", "массовый расстрел", "массовое убийство"],
        "hi": ["हत्या", "वध", "नरसंहार", "सामूहिक गोलीबारी", "सामूहिक हत्या", "सक्रिय शूटर"],
        "sr": ["атентат", "убиство", "покољ", "масакр", "масовна пуцњава", "масовно пуцање"],
    },
    "kidnapping": {
        "en": ["kidnapping", "abduction", "hijacking", "hostage situation"],
        "es": ["secuestro", "rapto", "secuestro forzoso", "toma de rehenes"],
        "fr": ["enlèvement", "rapt", "détournement", "prise d'otages"],
        "zh": ["綁架", "誘拐", "劫持", "人質事件"],
        "ru": ["похищение, угон", "захват заложников"],
        "hi": ["अपहरण", "बंधक स्थिति"],
        "sr": ["отмица", "киднаповање", "талачка ситуација"],
    },
    "human trafficking": {
        "en": ["human trafficking", "sex trafficking", "rape", "sexual assault", "violent crime"],
        "es": ["trata de personas", "tráfico sexual", "violación", "agresión sexual", "delitos violentos"],
        "fr": ["traite des êtres humains", "trafic sexuel", "viol", "agression sexuelle", "crime violent"],
        "zh": ["人口販賣", "性交易", "強暴", "性侵害", "暴力犯罪"],
        "ru": ["торговля людьми", "торговля людьми в целях сексуальной эксплуатации", "изнасилование", "сексуальное насилие", "насильственные преступления"],
        "hi": ["मानव तस्करी", "यौन तस्करी", "बलात्कार", "यौन उत्पीड़न", "हिंसक अपराध"],
        "sr": ["трговина људима", "силовање", "сексуални напад", "насилни злочин", "насиље"],
    },
     "terrorism": {
        "en": ["bombing", "improvised explosive device", "IED", "terrorist attack", "terrorism", "suicide bombing", "drone attack", "explosion", "road ambush"],
        "es": ["bombardeo", "artefacto explosivo improvisado", "ataque terrorista", "terrorismo", "atentado suicida", "ataque con drones", "explosión", "emboscada en la carretera"],
        "fr": ["attentat à la bombe", "engin explosif improvisé", "attaque terroriste", "terrorisme", "attentat suicide", "attaque de drone", "explosion", "embuscade routière"],
        "zh": ["轟炸", "簡易爆炸裝置", "恐怖攻擊", "恐怖主義", "自殺式爆炸", "無人機攻擊", "爆炸", "公路伏擊"],
        "ru": ["бомбардировка", "самодельное взрывное устройство", "теракт", "терроризм, теракт-смертник", "атака с использованием дронов", "взрыв", "дорожная засада"],
        "hi": ["बमबारी", "तात्कालिक विस्फोटक उपकरण", "आतंकवादी हमला", "आतंकवाद", "आत्मघाती बम विस्फोट", "ड्रोन हमला", "विस्फोट", "सड़क पर घात लगाकर हमला"],
        "sr": ["бомбардовање", "сачекуша", "импровизована експлозивна направа", "терористички напад", "тероризам", "самоубилачки бомбашки напад", "напад дроном", "експлозија", "заседа на путу", "бомбаш самоубица", "бомба"],
    },
    "military coup": {
        "en": ["military coup", "military raid", "coup d'etat", "regime change", "military takeover"],
        "es": ["golpe militar", "incursión militar", "golpe de estado", "cambio de régimen", "toma del poder militar"],
        "fr": ["coup d'État militaire", "raid militaire", "changement de régime", "prise de pouvoir militaire"],
        "zh": ["軍事政變", "軍事攻擊", "政變", "政權更迭", "軍事接管"],
        "ru": ["военный переворот", "военный рейд", "государственный переворот", "смена режима"],
        "hi": ["सैन्य तख्तापलट", "सैन्य छापा", "तख्तापलट", "शासन परिवर्तन", "सैन्य अधिग्रहण"],
        "sr": ["војни пуч", "војна рација", "државни удар", "промена власти", "војно преузимање власти"],
    },
     "state of emergency": {
        "en": ["state of emergency", "martial law", "curfew", "roadblock", "police raid"],
        "es": ["estado de emergencia", "ley marcial", "toque de queda", "bloqueo de carreteras", "redada policial"],
        "fr": ["état d'urgence", "loi martiale", "couvre-feu", "barrage routier", "descente de police"],
        "zh": ["緊急狀態", "戒嚴", "宵禁", "路障", "警察突襲"],
        "ru": ["чрезвычайное положение", "военное положение", "комендантский час", "блокирование дорог", "полицейский рейд"],
        "hi": ["आपातकालीन स्थिति", "मार्शल लॉ", "कर्फ्यू", "सड़क अवरोध", "पुलिस छापा"],
        "sr": ["ванредно стање", "војно стање", "полицијски час", "блокада пута", "полицијска рација"],
    },
    "protest": {
        "en": ["civil unrest", "riot", "protest", "political unrest", "uprising", "insurrection", "political turmoil", "political crisis", "demonstration"],
        "es": ["disturbios civiles", "disturbios", "protestas", "disturbios políticos", "levantamientos", "insurrecciones", "agitación política", "crisis política"],
        "fr": ["troubles civils", "émeute", "protestation", "soulèvement", "insurrection", "troubles politiques", "crise politique"],
        "zh": ["國內暴動", "暴動", "抗議", "政治動亂", "起義", "叛亂", "政治動盪", "政治危機", "示威"],
        "ru": ["гражданские беспорядки", "бунт", "протест", "политические беспорядки", "восстание, мятеж", "политические волнения", "политический кризис", "демонстрация"],
        "hi": ["नागरिक अशांति", "दंगा", "विरोध", "राजनीतिक अशांति", "विद्रोह", "बगावत", "राजनीतिक उथल-पुथल", "राजनीतिक संकट", "प्रदर्शन"],
        "sr": ["грађански немири", "протест", "политички немири", "демонстрације", "политичко превирање", "политичка криза"],
    },
    "border closure": {
        "en": ["border closure", "flight cancellation", "airport closure", "lockdown"],
        "es": ["cierre de fronteras", "cancelación de vuelos", "cierre de aeropuertos"],
        "fr": ["fermeture des frontières", "annulation de vol", "fermeture de l'aéroport"],
        "zh": ["邊境關閉", "航班取消", "機場關閉", "封鎖"],
        "ru": ["закрытие границ", "отмена рейсов", "закрытие аэропортов", "локдаун"],
        "hi": ["सीमा बंद", "उड़ान रद्द", "हवाई अड्डा बंद", "लॉकडाउन"],
        "sr": ["затварање границе", "отказивање лета", "затварање аеродрома"],
    },
     "embassy alert": {
        "en": ["embassy alert", "travel advisory", "travel ban", "security alert"],
        "es": ["alerta de embajada", "aviso de viaje", "prohibición de viajar", "alerta de seguridad"],
        "fr": ["alerte de l'ambassade", "avis aux voyageurs", "interdiction de voyager", "alerte de sécurité"],
        "zh": ["大使館警報", "旅行警告", "旅行禁令", "安全警報"],
        "ru": ["оповещение посольства", "рекомендация по поездкам", "запрет на поездки", "предупреждение о безопасности"],
        "hi": ["दूतावास अलर्ट", "यात्रा सलाह", "यात्रा प्रतिबंध", "सुरक्षा अलर्ट"],
        "sr": ["упозорење амбасаде", "савет за путовања", "забрана путовања", "безбедносно упозорење"],
    },
    "evacuation": {
        "en": ["emergency situation", "evacuation", "government crisis", "war", "armed conflict"],
        "es": ["situación de emergencia", "evacuación", "crisis gubernamental", "guerra", "conflicto armado"],
        "fr": ["situation d'urgence", "évacuation", "crise gouvernementale", "guerre", "conflit armé"],
        "zh": ["緊急情況", "疏散", "政府危機", "戰爭", "武裝衝突"],
        "ru": ["чрезвычайная ситуация", "эвакуация", "правительственный кризис", "война", "вооруженный конфликт"],
        "hi": ["आपातकालीन स्थिति", "निकासी", "सरकारी संकट", "युद्ध", "सशस्त्र संघर्ष"],
        "sr": ["ванредна ситуација", "евакуација", "криза владе", "криза режима", "криза власти", "рат", "оружани сукоб"],
    },
    "pandemic": {
        "en": ["pandemic", "viral outbreak", "disease spread", "contamination", "quarantine"],
        "es": ["pandemia", "brote viral", "propagación de enfermedades", "contaminación", "cuarentena"],
        "fr": ["pandémie", "épidémie virale", "propagation de maladie", "contamination", "quarantaine"],
        "zh": ["大流行", "病毒爆發", "疾病傳播", "污染", "隔離"],
        "ru": ["пандемия", "вирусная вспышка", "распространение болезни", "заражение", "карантин"],
        "hi": ["महामारी", "वायरल प्रकोप", "रोग प्रसार", "संदूषण", "संगरोध"],
        "sr": ["пандемија", "контаминација", "карантин", "ширење вируса", "ширење заразе", "ширење болести"],
    },
    "epidemic": {
        "en": ["public health emergency", "infectious disease", "epidemic", "biological threat", "health alert"],
        "es": ["emergencia de salud pública", "enfermedad infecciosa", "epidemia", "amenaza biológica", "alerta sanitaria"],
        "fr": ["urgence de santé publique", "maladie infectieuse", "épidémie", "menace biologique", "alerte sanitaire"],
        "zh": ["突發公共衛生事件", "傳染病", "流行病", "生物威脅", "健康警報"],
        "ru": ["чрезвычайная ситуация в области общественного здравоохранения", "инфекционное заболевание", "эпидемия", "биологическая угроза", "оповещение о состоянии здоровья"],
        "hi": ["सार्वजनिक स्वास्थ्य आपातकाल", "संक्रामक रोग", "महामारी", "जैविक खतरा", "स्वास्थ्य चेतावनी"],
        "sr": ["епидемија", "заразне болести", "инфективне болести", "медицинска ванредна ситуација", "биолошка претња", "здравствено упозорење"],
    },
    "cyberattack": {
        "en": ["data breach", "ransomware", "cyberattack", "hacktivism", "deepfake", "phishing"],
        "es": ["violación de datos", "ransomware", "ciberataque", "hacktivismo", "deepfake", "phishing"],
        "fr": ["violation de données", "rançongiciel", "cyberattaque", "hacktivisme", "deepfake", "phishing"],
        "zh": ["資料外洩", "勒索軟體", "網路攻擊", "駭客行動主義", "深度偽造", "網路釣魚"],
        "ru": ["утечка данных", "программы-вымогатели", "кибератака", "хактивизм", "дипфейк", "фишинг"],
        "hi": ["डेटा उल्लंघन", "रैंसमवेयर", "साइबर हमला", "हैकटिविज़्म", "डीपफेक", "फ़िशिंग"],
        "sr": ["крађа података", "рансомвер", "сајбер напад", "хактивизам", "дипфејк", "фишинг", "нарушавање приватности"],
    },
    "cyber espionage": {
        "en": ["malware", "cyber espionage", "identity theft", "network breach", "online scam"],
        "es": ["malware", "ciberespionaje", "robo de identidad", "violación de la red", "estafa en línea"],
        "fr": ["logiciels malveillants", "cyberespionnage", "vol d'identité", "violation de réseau", "escroquerie en ligne"],
        "zh": ["惡意軟體", "網路間諜", "身分盜竊", "網路入侵", "網路詐騙"],
        "ru": ["вредоносное ПО", "кибершпионаж", "кража личных данных", "взлом сети", "интернет-мошенничество"],
        "hi": ["मैलवेयर", "साइबर जासूसी", "पहचान की चोरी", "नेटवर्क उल्लंघन", "ऑनलाइन घोटाला"],
        "sr": ["злонамерни софтвер", "сајбер шпијунажа", "крађа идентитета", "хаковање мреже", "онлајн превара"],
    },
     "digital kidnapping": {
        "en": ["digital kidnapping", "virtual kidnapping", "cyber kidnapping", "honey trap", "hacking attack"],
        "es": ["secuestro digital", "secuestro virtual", "secuestro cibernético", "trampa de miel", "ataque de hackers"],
        "fr": ["enlèvement numérique", "enlèvement virtuel", "cyber-enlèvement", "piège à miel", "attaque de piratage"],
        "zh": ["大流行", "病毒爆發", "疾病傳播", "污染", "隔離"],
        "ru": ["пандемия", "вирусная вспышка", "распространение болезни", "заражение", "карантин"],
        "hi": ["महामारी", "वायरल प्रकोप", "रोग प्रसार", "संदूषण", "संगरोध"],
        "sr": ["дигитална отмица", "виртуелна отмица", "сајбер отмица", "хакерски напад", "хаковање"],
    },
     "cyber fraud": {
        "en": ["cyber fraud", "crypto fraud", "financial scam", "organized crime"],
        "es": ["fraude cibernético", "fraude de criptomonedas", "estafa financiera", "crimen organizado"],
        "fr": ["cyberfraude", "fraude cryptographique", "escroquerie financière", "crime organisé"],
        "zh": ["網路詐騙", "加密貨幣詐騙", "金融詐騙", "組織犯罪"],
        "ru": ["кибермошенничество", "криптомошенничество", "финансовое мошенничество", "организованная преступность"],
        "hi": ["साइबर धोखाधड़ी", "क्रिप्टो धोखाधड़ी", "वित्तीय घोटाला", "संगठित अपराध"],
        "sr": ["сајбер превара", "крипто превара", "финансијска превара", "организовани криминал"],
    },
    "travel scam": {
        "en": ["travel scam", "armed robbery", "assault on a foreigner", "assault on a tourist"],
        "es": ["estafa de viaje", "robo a mano armada", "asalto a un extranjero", "asalto a un turista"],
        "fr": ["arnaque au voyage", "vol à main armée", "agression d'un étranger", "agression d'un touriste"],
        "zh": ["旅行詐騙", "武裝搶劫", "襲擊外國人", "襲擊遊客"],
        "ru": ["Мошенничество в сфере туризма", "вооруженные ограбления", "нападения на иностранцев", "нападения на туристов"],
        "hi": ["यात्रा घोटाला", "सशस्त्र डकैती", "विदेशी पर हमला", "पर्यटक पर हमला"],
        "sr": ["превара у путовању", "оружана пљачка", "напад на странца", "напад на туристу", "масовна туча", "насиље на улици", "туча навијача", "насилничко понашање", "претучена", "претучен", "покушај убиства", "претукао"],
    },
    "jihadist": {
        "en": ["extremist activity", "radicalization", "jihadist", "pirate attack"],
        "es": ["actividad extremista", "radicalización", "yihadista", "ataque pirata"],
        "fr": ["activité extrémiste", "radicalisation", "djihadiste", "attaque de pirates"],
        "zh": ["極端主義活動", "激進主義", "聖戰士", "海盜襲擊"],
        "ru": ["экстремистская деятельность", "радикализация", "джихад", "пиратская атака"],
        "hi": ["चरमपंथी गतिविधि", "कट्टरपंथ", "जिहादी", "समुद्री डाकू हमला"],
        "sr": ["екстремистички напад", "радикализација", "џихадисти", "пиратски напад", "исламисти"],
    },
    "extremism": {
        "en": ["extremism", "armed groups", "militia attacks", "armed militants", "separatists"],
        "es": ["extremismo", "grupos armados", "ataques de milicias", "militantes armados", "separatistas"],
        "fr": ["extrémisme", "groupes armés", "attaques de milices", "militants armés", "séparatistes"],
        "zh": ["極端主義", "武裝團體", "民兵襲擊", "武裝份子", "分離主義者"],
        "ru": ["экстремизм", "вооруженные группы", "нападения ополченцев", "вооруженные боевики", "сепаратисты"],
        "hi": ["उग्रवाद, सशस्त्र समूह", "मिलिशिया हमले", "सशस्त्र आतंकवादी", "अलगाववादी"],
        "sr": ["екстремизам", "наоружане групе", "напади милиције", "наоружани милитанти", "сепаратисти"],
    },
    "natural disaster": {
        "en": ["natural disaster", "earthquake", "tsunami", "tornado", "hurricane", "flood", "wild fire"],
        "es": ["desastre natural", "terremoto", "tsunami", "tornado", "huracán", "inundación", "incendio forestal"],
        "fr": ["catastrophe naturelle", "tremblement de terre", "tsunami", "tornade", "ouragan", "inondation", "feu de forêt"],
        "zh": ["自然災害, 地震, 海嘯, 龍捲風, 颶風, 洪水, 野火"],
        "ru": ["стихийное бедствие", "землетрясение", "цунами", "торнадо", "ураган", "наводнение", "лесной пожар"],
        "hi": ["प्राकृतिक आपदा", "भूकंप", "सुनामी", "बवंडर", "तूफान", "बाढ़", "जंगली आग"],
        "sr": ["природна катастрофа", "земљотрес", "цунами", "торнадо", "ураган", "поплава", "поплаве", "шумски пожар"],
    },
    "police brutality": {
        "en": ["police brutality", "brutal attack", "false imprisonment", "blackmail", "extortion"],
        "es": ["brutalidad policial", "ataque brutal", "encarcelamiento injusto", "chantaje", "extorsión"],
        "fr": ["brutalité policière", "attaque brutale", "séquestration", "chantage", "extorsion"],
        "zh": ["警察暴力", "野蠻攻擊", "非法監禁", "敲詐勒索", "勒索"],
        "ru": ["жестокость полиции", "жестокое нападение", "незаконное лишение свободы", "шантаж", "вымогательство"],
        "hi": ["पुलिस की बर्बरता", "क्रूर हमला", "झूठा कारावास", "ब्लैकमेल", "जबरन वसूली"],
        "sr": ["полицијска бруталност", "бруталан напад", "незаконито затварање", "уцена", "изнуда", "рекетирање"],
    },                                 

}

def first_sentence(text):
    import re
    sentences = re.split(r'(?<=[.!?。！？\n])\s+', text.strip())
    return sentences[0] if sentences else text

def any_multilingual_keyword(text, lang, TRANSLATED_KEYWORDS):
    text = text.lower()
    for threat, lang_map in TRANSLATED_KEYWORDS.items():
        roots = lang_map.get(lang, [])
        for root in roots:
            if root in text:
                return threat
    return None

def safe_detect_lang(text, default="en"):
    try:
        if len(text.strip()) < 10:
            return default
        return detect(text)
    except Exception:
        return default

NORMALIZED_LOCAL_FEEDS = {unidecode(city).lower().strip(): v for city, v in LOCAL_FEEDS.items()}

def get_feed_for_city(city):
    if not city:
        return None
    city_key = unidecode(city).lower().strip()
    match = difflib.get_close_matches(city_key, NORMALIZED_LOCAL_FEEDS.keys(), n=1, cutoff=0.8)
    if match:
        return NORMALIZED_LOCAL_FEEDS[match[0]]
    return None

def get_feed_for_location(region=None, city=None, topic=None):
    region_key = region.strip().title() if region else None
    if region_key and region_key in FCDO_FEEDS:
        return [FCDO_FEEDS[region_key]]
    city_feeds = get_feed_for_city(city)
    if city_feeds:
        return city_feeds
    if topic and topic.lower() == "cyber":
        try:
            from feeds_catalog import CYBER_FEEDS
            return CYBER_FEEDS
        except ImportError:
            pass
    region_key_lower = region.lower().strip() if region else None
    if region_key_lower and region_key_lower in COUNTRY_FEEDS:
        return COUNTRY_FEEDS[region_key_lower]
    return GLOBAL_FEEDS

# --- Security-focused summarizer with caching ---
def summarize_with_security_focus(text):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": SECURITY_SUMMARIZE_PROMPT + "\n\n" + text}
    ]
    grok_summary = grok_chat(messages)
    if grok_summary:
        return grok_summary
    if openai_client:
        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0.3
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.info(f"[OpenAI fallback error] {e}")
    return "No summary available due to an error."

def summarize_with_security_focus_cached(summarize_fn):
    cache_file = "summary_cache.json"
    Path(cache_file).touch(exist_ok=True)
    try:
        with open(cache_file, "r") as f:
            cache = json.load(f)
    except json.JSONDecodeError:
        cache = {}
    def wrapper(text):
        key = sha256(text.encode("utf-8")).hexdigest()
        if key in cache:
            return cache[key]
        summary = summarize_fn(text)
        cache[key] = summary
        with open(cache_file, "w") as f:
            json.dump(cache, f, indent=2)
        return summary
    return wrapper

summarize_with_security_grok = summarize_with_security_focus_cached(summarize_with_security_focus)

# --- Plan limits for LLM summaries ---
PLAN_LIMITS = {
    "FREE": {"monthly": 5, "per_session": 2},
    "BASIC": {"monthly": 20, "per_session": 5},
    "PRO": {"monthly": 50, "per_session": 10},
    "VIP": {"monthly": float("inf"), "per_session": float("inf")},
}

def should_summarize_alert(alert, plan, used_count=0, session_count=0):
    if plan.upper() == "VIP":
        return True
    is_high_risk = (alert.get("score", 0) >= 0.75 or alert.get("level", "").lower() in ("high", "critical"))
    limits = PLAN_LIMITS.get(plan.upper(), PLAN_LIMITS["FREE"])
    if is_high_risk and used_count < limits["monthly"] and session_count < limits["per_session"]:
        return True
    return False

# Usage tracking functions
from datetime import datetime

def atomic_increment_and_check(redis_client, key, limit, expiry):
    try:
        # Atomically increment the count
        count = redis_client.incr(key)
        # Set expiry only if the key is new
        if count == 1 and expiry:
            redis_client.expire(key, expiry)
        return count <= limit
    except Exception as e:
        logger.error(f"[Redis][atomic_increment_and_check] {e}")
        return False

def can_user_summarize(redis_client, user_id, plan_limits):
    month = datetime.utcnow().strftime("%Y-%m")
    key = f"user:{user_id}:llm_alert_count:{month}"
    expiry = 60 * 60 * 24 * 45  # 45 days
    return atomic_increment_and_check(redis_client, key, plan_limits["monthly"], expiry)

def can_session_summarize(redis_client, session_id, plan_limits):
    key = f"session:{session_id}:llm_alert_count"
    expiry = 60 * 60 * 24  # 24 hours
    return atomic_increment_and_check(redis_client, key, plan_limits["per_session"], expiry)

THREAT_CATEGORIES = [
    "Terrorism", "Protest", "Crime", "Kidnapping", "Cyber",
    "Natural Disaster", "Political", "Infrastructure", "Health", "Unclassified"
]

def classify_threat_type(text):
    import json as pyjson
    messages = [
        {"role": "system", "content": "You are a threat classifier. Respond with a JSON as: {\"label\": ..., \"confidence\": ...}"},
        {"role": "user", "content": TYPE_PROMPT + "\n\n" + text}
    ]
    try:
        grok_label = grok_chat(messages, temperature=0)
        if grok_label:
            try:
                parsed = pyjson.loads(grok_label)
                label = parsed.get("label", "Unclassified")
                confidence = float(parsed.get("confidence", 0.85))
            except Exception:
                label = grok_label.strip()
                confidence = 0.88 if label in THREAT_CATEGORIES else 0.5
            if label not in THREAT_CATEGORIES:
                label = "Unclassified"
                confidence = 0.5
            return {"label": label, "confidence": confidence}
    except Exception as e:
        logger.error(f"[classify_threat_type][Grok error] {e}")

    if openai_client:
        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0
            )
            try:
                parsed = pyjson.loads(response.choices[0].message.content)
                label = parsed.get("label", "Unclassified")
                confidence = float(parsed.get("confidence", 0.85))
            except Exception:
                label = response.choices[0].message.content.strip()
                confidence = 0.85 if label in THREAT_CATEGORIES else 0.5
            if label not in THREAT_CATEGORIES:
                label = "Unclassified"
                confidence = 0.5
            return {"label": label, "confidence": confidence}
        except Exception as e:
            logger.error(f"[classify_threat_type][OpenAI error] {e}")

    return {"label": "Unclassified", "confidence": 0.5}

def fetch_feed(url, timeout=7, retries=3, backoff=1.5, max_backoff=60):
    attempt = 0
    current_backoff = backoff
    while attempt < retries:
        try:
            response = httpx.get(url, timeout=timeout)
            if response.status_code == 200:
                logger.info(f"✅ Fetched: {url}")
                return feedparser.parse(response.content.decode('utf-8', errors='ignore')), url
            elif response.status_code in [429, 503]:
                current_backoff = min(current_backoff * 2, max_backoff)
                logger.warning(f"⚠️ Throttled ({response.status_code}) by {url}; backing off for {current_backoff} seconds")
                time.sleep(current_backoff)
            else:
                logger.warning(f"⚠️ Feed returned {response.status_code}: {url}")
        except Exception as e:
            logger.warning(f"❌ Attempt {attempt + 1} failed for {url} — {e}")
        attempt += 1
        time.sleep(current_backoff)
    logger.warning(f"❌ Failed to fetch after {retries} retries: {url}")
    return None, url

def llm_is_alert_relevant(alert, region=None, city=None):
    location = ""
    if city and region:
        location = f"{city}, {region}"
    elif city:
        location = city
    elif region:
        location = region
    else:
        return False
    text = (alert.get("title", "") + " " + alert.get("summary", ""))
    prompt = (
        f"Is the following security alert directly relevant to {location}? "
        "Be strict: Only answer Yes if the alert concerns events happening in, targeting, or otherwise mentioning this location. "
        "If it's general, about another country/region, or does not mention this location, answer No.\n\n"
        f"Alert:\n{text}\n\n"
        "Reply with only Yes or No."
    )
    messages = [{"role": "user", "content": prompt}]
    answer = grok_chat(messages, temperature=0)
    if answer:
        answer = answer.strip().lower()
        if answer.startswith("yes"):
            return True
        if answer.startswith("no"):
            return False
    if openai_client:
        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0
            )
            txt = response.choices[0].message.content.strip().lower()
            if txt.startswith("yes"):
                return True
            if txt.startswith("no"):
                return False
        except Exception as e:
            logger.error(f"[LLM relevance fallback error] {e}")
    return False

def filter_alerts_llm(alerts, region=None, city=None, max_workers=4):
    args = [(alert, region, city) for alert in alerts]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        relevant_flags = list(executor.map(lambda ac: llm_is_alert_relevant(*ac), args))
    filtered = []
    for i, flag in enumerate(relevant_flags):
        if flag:
            filtered.append(alerts[i])
    return filtered

def map_severity(score):
    if score is None:
        return "Unknown"
    if score >= 0.75:
        return "High"
    if score >= 0.45:
        return "Medium"
    return "Low"

# --- Translation logic (LibreTranslate & googletrans fallback) ---
translator = Translator()
translation_cache = {}

def translate_snippet(snippet, lang):
    if len(snippet.strip()) < 10 or lang == "en":
        return snippet
    key = sha256((snippet + lang).encode("utf-8")).hexdigest()
    if key in translation_cache:
        return translation_cache[key]
    # Try LibreTranslate first
    try:
        response = requests.post(
            "https://libretranslate.com/translate",
            data={"q": snippet, "source": lang, "target": "en", "format": "text"},
            timeout=10
        )
        response.raise_for_status()
        translated = response.json().get("translatedText", None)
        if translated:
            translation_cache[key] = translated
            return translated
    except Exception as e:
        logger.error(f"[LibreTranslate error] {e}")
    # Fallback to googletrans
    try:
        result = translator.translate(snippet, src=lang, dest='en')
        translated = result.text
        translation_cache[key] = translated
        return translated
    except Exception as e:
        logger.error(f"[googletrans error] {e}")
    translation_cache[key] = snippet
    return snippet

def get_clean_alerts(
    region=None, topic=None, city=None, limit=20, summarize=False,
    llm_location_filter=True, plan="FREE", user_id=None, session_id=None
):
    alerts = []
    seen = set()
    region_str = str(region).strip() if region else None
    topic_str = str(topic).lower() if isinstance(topic, str) and topic else "all"
    city_str = str(city).strip() if city else None

    feeds = get_feed_for_location(region=region_str, city=city_str, topic=topic_str)
    if not feeds:
        logger.info("⚠️ No feeds found for the given location/topic.")
        return []

    with ThreadPoolExecutor(max_workers=len(feeds)) as executor:
        results = list(executor.map(fetch_feed, feeds))

    for feed, source_url in results:
        if not feed or 'entries' not in feed:
            continue

        source_domain = urlparse(source_url).netloc.replace("www.", "")
        for entry in feed.entries:
            title = entry.get("title", "").strip()
            summary = entry.get("summary", "").strip()
            subtitle = first_sentence(summary)
            search_text = f"{title}. {subtitle}".lower()
            link = entry.get("link", "").strip()
            published = entry.get("published", "")

            # Detect language
            lang = safe_detect_lang(search_text)

            # Multilingual and English keyword matching
            threat_match = any_multilingual_keyword(search_text, lang, TRANSLATED_KEYWORDS)
            english_match = KEYWORD_PATTERN.search(search_text)

            if not (threat_match or english_match):
                continue

            # Only translate if not English
            snippet = f"{title}. {summary}".strip()
            if lang != "en":
                en_snippet = translate_snippet(snippet, lang)
            else:
                en_snippet = snippet

            dedupe_key = sha256(f"{title}:{subtitle}".encode("utf-8")).hexdigest()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            alert = {
                "uuid": dedupe_key,
                "title": title,
                "summary": summary,
                "en_snippet": en_snippet,
                "gpt_summary": "",
                "link": link,
                "source": source_domain,
                "published": published,
                "region": region_str,
                "city": city_str,
                "type": "",
                "type_confidence": None,
                "level": "",
                "threat_label": "",
                "score": None,
                "confidence": None,
                "reasoning": "",
                "review_flag": False,
                "review_notes": "",
                "timestamp": datetime.utcnow().isoformat(),
                "model_used": "",
            }
            try:
                alert_text = f"{title}: {summary}"
                threat_result = assess_threat_level(
                    alert_text=alert_text,
                    triggers=[],
                    location=city or region or "",
                    alert_uuid=dedupe_key,
                    plan=plan
                )
                for k, v in threat_result.items():
                    alert[k] = v
                alert["level"] = alert.get("threat_label", "")
            except Exception as e:
                logger.error(f"[RSS_PROCESSOR_ERROR][THREAT_SCORER] {e} | Alert: {title}")
                alert["threat_label"] = "Unrated"
                alert["score"] = 0
                alert["reasoning"] = f"Threat scorer failed: {e}"
                alert["confidence"] = 0.0
                alert["review_flag"] = True
                alert["review_notes"] = "Could not auto-score threat; requires analyst review."
                alert["timestamp"] = datetime.utcnow().isoformat()
                alert["level"] = "Unknown"

            try:
                threat_type = classify_threat_type(summary)
                alert["type"] = threat_type["label"]
                alert["type_confidence"] = threat_type["confidence"]
            except Exception as e:
                logger.error(f"[RSS_PROCESSOR_ERROR][ThreatType] {e} | Alert: {title}")
                alert["type"] = "Unclassified"
                alert["type_confidence"] = 0.5

            alerts.append(alert)

            if len(alerts) >= limit:
                logger.info(f"✅ Parsed {len(alerts)} alerts.")
                break
        if len(alerts) >= limit:
            break

    filtered_alerts = []
    if llm_location_filter and (city_str or region_str):
        logger.info("🔍 Running LLM-based location relevance filtering...")
        filtered_alerts = filter_alerts_llm(alerts, region=region_str, city=city_str)
    else:
        filtered_alerts = alerts

    if not filtered_alerts:
        logger.error("⚠️ No relevant alerts found for city/region. Will use fallback advisory.")
        return []

    # ---- PLAN-AWARE, SECURITY-FOCUSED LLM SUMMARY LOGIC ----
    if summarize and filtered_alerts:
       plan_limits = PLAN_LIMITS.get(plan.upper(), PLAN_LIMITS["FREE"])
       for alert in filtered_alerts:
           if should_summarize_alert(alert, plan):  # No more batch quota params
               user_ok = can_user_summarize(redis_client, user_id, plan_limits)
               session_ok = can_session_summarize(redis_client, session_id, plan_limits)
               if user_ok and session_ok:
                   summary = summarize_with_security_grok(alert["en_snippet"])
                   alert["gpt_summary"] = summary
               else:
                   alert["gpt_summary"] = ""
                   logger.info(f"Quota exceeded for {user_id=} or {session_id=}")
           else:
                alert["gpt_summary"] = ""
    else:
       for alert in filtered_alerts:
           alert.setdefault("gpt_summary", "")     

    logger.info(f"✅ Parsed {len(filtered_alerts)} location-relevant alerts.")
    return filtered_alerts[:limit]

def get_clean_alerts_cached(get_clean_alerts_fn):
    def wrapper(*args, **kwargs):
        summarize = kwargs.get("summarize", False)
        region = kwargs.get("region", None)
        city = kwargs.get("city", None)
        topic = kwargs.get("topic", None)

        if summarize or region or city or topic:
            return get_clean_alerts_fn(*args, **kwargs)

        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        cache_dir = "cache"
        Path(cache_dir).mkdir(exist_ok=True)
        cache_path = os.path.join(cache_dir, f"alerts-{today_str}.json")

        if os.path.exists(cache_path):
            with open(cache_path, "r") as f:
                logger.info(f"[CACHE] Loaded alerts from cache: {cache_path}")
                return json.load(f)

        alerts = get_clean_alerts_fn(*args, **kwargs)
        with open(cache_path, "w") as f:
            json.dump(alerts, f, indent=2)
        logger.info(f"✅ Saved {len(alerts)} alerts to cache: {cache_path}")
        return alerts

    return wrapper

def generate_fallback_summary(region, threat_type, city=None):
    location = f"{city}, {region}" if city and region else (city or region or "your location")
    prompt = FALLBACK_PROMPT.format(location=location, threat_type=threat_type)
    messages = [{"role": "user", "content": prompt}]
    grok_summary = grok_chat(messages, temperature=0.4)
    if grok_summary:
        return grok_summary
    if openai_client:
        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0.4
            )
            return response.choices[0].message.content.strip()
        except Exception as e2:
            return f"⚠️ Fallback error: {str(e2)}"
    return f"⚠️ Fallback error: Could not generate summary."

get_clean_alerts = get_clean_alerts_cached(get_clean_alerts)

if __name__ == "__main__":
    logger.info("🔍 Running standalone RSS processor...")
    alerts = get_clean_alerts(region="Afghanistan", limit=5, summarize=True, plan="VIP", user_id="demo", session_id="demo")
    if not alerts:
        logger.info("No relevant alerts found. Generating fallback advisory...")
        logger.info(generate_fallback_summary(region="Afghanistan", threat_type="All"))
    else:
        for alert in alerts:
            logger.info(json.dumps(alert, indent=2))