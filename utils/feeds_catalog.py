"""
feeds_catalog.py — Curated news/alert feed catalogs
Used by rss_processor.py with native-first priority (local > country > global).
"""

# ---------------------- City to Country Mapping ----------------------
# Canonical mapping from city names to their correct countries
# Used to ensure proper location extraction from feed source_tags
CITY_TO_COUNTRY = {
    "anchorage": "United States",
    "belgrade": "Serbia",
    "hong kong": "Hong Kong",
    "paris": "France",
    "new york": "United States",
    "los angeles": "United States",
    "san diego": "United States",
    "san francisco": "United States",
        "denver": "United States",
        "durango": "United States",
        "phoenix": "United States",
        "tucson": "United States",
        "new london": "United States",
        "miami": "United States",
    "atlanta": "United States",
    "honolulu": "United States",
    "chicago": "United States",
    "indianapolis": "United States",
    "kansas city": "United States",
    "mumbai": "India",
    "moscow": "Russia",
    "sydney": "Australia",
    "rome": "Italy",
    "delhi": "India",
    "rio de janeiro": "Brazil",
    "singapore": "Singapore",
    "buenos aires": "Argentina",
    "karachi": "Pakistan",
    "manila": "Philippines",
    "port moresby": "Papua New Guinea",
    "boston": "United States",
    "washington": "United States",
    "miami": "United States",
    "houston": "United States",
    "amsterdam": "Netherlands",
    "vienna": "Austria",
    "zurich": "Switzerland",
    "brussels": "Belgium",
    "stockholm": "Sweden",
    "oslo": "Norway",
    "helsinki": "Finland",
    "copenhagen": "Denmark",
    "prague": "Czech Republic",
    "budapest": "Hungary",
    "cluj": "Romania",
    "arad": "Romania",
    "bucharest": "Romania",
    "sofia": "Bulgaria",
    "plovdiv": "Bulgaria",
    "haskovo": "Bulgaria",
    "athens": "Greece",
    "ankara": "Turkey",
    "istanbul": "Turkey",
    "berlin": "Germany",
    "munich": "Germany",
    "saint petersburg": "Russia",
    "kyiv": "Ukraine",
    "minsk": "Belarus",
    "tel aviv": "Israel",
    "dubai": "United Arab Emirates",
    "riyadh": "Saudi Arabia",
    "tehran": "Iran",
    "baghdad": "Iraq",
    "beirut": "Lebanon",
    "damascus": "Syria",
    "cali": "Colombia",
    "lima": "Peru",
    "caracas": "Venezuela",
    "bogota": "Colombia",
    "nairobi": "Kenya",
    "casablanca": "Morocco",
    "algiers": "Algeria",
    "addis ababa": "Ethiopia",
    "lagos": "Nigeria",
    "accra": "Ghana",
    "abidjan": "Ivory Coast",
    "cotonou": "Benin",
    "kinshasa": "DR Congo",
    "jeddah": "Saudi Arabia",
    "doha": "Qatar",
    "kuwait city": "Kuwait",
    "kuala lumpur": "Malaysia",
    "bangkok": "Thailand",
    "hanoi": "Vietnam",
    "jakarta": "Indonesia",
    "melbourne": "Australia",
    "auckland": "New Zealand",
    "perth": "Australia",
    "brisbane": "Australia",
    "montreal": "Canada",
    "vancouver": "Canada",
    "calgary": "Canada",
    "ottawa": "Canada",
    "toronto": "Canada",
    "edmonton": "Canada",
    "birmingham": "United States",
    "tuscaloosa": "United States",
    "mountain brook": "United States",
    "seldovia": "United States",
    "quebec city": "Canada",
    "winnipeg": "Canada",
    "halifax": "Canada",
    "st johns": "Canada",
    "cape town": "South Africa",
    "novi sad": "Serbia",
    "nis": "Serbia",
    "sankt petersburg": "Russia",
    "tallinn": "Estonia",
    "trieste": "Italy",
    "jerusalem": "Israel",
}

# =====================================================================
# ENGLISH-ONLY GLOBAL FEEDS STRATEGY
# =====================================================================
# Focus: Global English-language sources with location extraction
# Location extraction happens via content analysis (city_utils/location_service)
# No more relying on non-English local feeds that create noise
# 
# Benefits:
# - Higher quality, accurate reporting
# - No translation issues/keyword mismatches
# - Proper city/country extraction from article content
# - Reduced noise and false positives
# =====================================================================

# ---------------------- Local city feeds (ENGLISH ONLY) ----------------------
# Only keeping major English-language city feeds
LOCAL_FEEDS = {
    "anchorage": ["https://www.fbi.gov/feeds/anchorage-news/RSS"],
    "hong kong": [
        "https://www.scmp.com/rss/2/feed/",
        "https://globalvoices.org/-/world/east-asia/hong-kong-china/feed/"
        ],
    "jerusalem": ["https://www.jpost.com/rss/rssfeedsjerusalem.aspx"],
    "istanbul": ["https://www.dailysabah.com/rss/turkiye/istanbul"],
    "new york": [
        "https://nypost.com/tag/new-york-city/feed/",
        "https://www.fbi.gov/feeds/newyork-news/RSS"
    ],
    "los angeles": [
        "https://www.latimes.com/local/rss2.0.xml",
        "https://feeds.feedburner.com/breitbart",
        "https://www.fbi.gov/feeds/losangeles-news/RSS"
    ],
    "denver": [
        "https://feeds.denversun.com/rss/73aa4032e9682bab",
        "https://www.fbi.gov/feeds/denver-news/RSS"
    ],
    "durango": [
        "https://durangodowntown.com/feed/",
        "https://www.durangoherald.com/rss-feeds/"
    ],
    "phoenix": [
        "https://feeds.phoenixherald.com/rss/caf48823f1822eb3",
        "https://www.fbi.gov/feeds/phoenix-news/RSS"
    ],
    "tucson": ["https://feeds.tucsonpost.com/rss/a548abef580c2494"],
    "new london": ["https://theday.com/live-content/rss/"],
    "miami": [
        "https://feeds.miamimirror.com/rss/9406bbb67f053bb2",
        "https://www.fbi.gov/feeds/miami-news/RSS"
    ],
    "atlanta": [
        "https://feeds.atlantaleader.com/rss/ffe56b8f30c50146",
        "https://theatlantavoice.com/feed/",
        "https://www.fbi.gov/feeds/atlanta-news/RSS"
    ],
    "honolulu": [
        "https://www.civilbeat.org/feed/",
        "https://feeds.hawaiitelegraph.com/rss/6b17ec7a35065289",
        "https://www.hawaiifreepress.com/DesktopModules/DnnForge%20-%20NewsArticles/RSS.aspx?TabID=56&ModuleID=380&MaxCount=25"
    ],
    "chicago": [
        "https://feeds.chicagochronicle.com/rss/c8ac3000ee01c7aa",
        "https://www.fbi.gov/feeds/chicago-news/RSS"
    ],
    "indianapolis": [
        "https://thedepauw.com/feed/",
        "https://feeds.indianapolispost.com/rss/43a9fd3724cda141"
    ],
    "kansas city": ["https://feeds.kansascitypost.com/rss/cc264e50ceab3697"],
    "san diego": ["https://timesofsandiego.com/feed/"],
    "san francisco": [
        "https://el-observador.com/feed/",
        "https://www.fbi.gov/feeds/sanfrancisco-news/RSS"
    ],
    "sydney": ["https://www.abc.net.au/news/feed/2942460/rss.xml"],
    "singapore": ["https://www.straitstimes.com/news/singapore/rss.xml"],
    "manila": ["https://www.philstar.com/rss/nation"],
    "port moresby": ["https://feeds.feedburner.com/pngfacts/PcXZ"],
    "boston": [
        "https://www.boston.com/tag/local-news/feed/",
        "https://www.fbi.gov/feeds/boston-news/RSS"
    ],
    "washington": [
        "https://wtop.com/local/feed/",
        "https://feeds.washingtonpost.com/rss/local?itid=sf_local",
        "https://www.fbi.gov/feeds/washington-news/RSS"
    ],
    "houston": [
        "https://www.click2houston.com/arc/outboundfeeds/rss/category/news/local/?outputType=xml&size=10",
        "https://www.fbi.gov/feeds/houston-news/RSS"
    ],
    "birmingham": ["https://feeds.birminghamstar.com/rss/0cd1f7701040892f"],
    "tuscaloosa": ["https://feeds.tuscaloosatimes.com/rss/7e50c85536b0a892"],
    "mountain brook": ["https://www.villagelivingonline.com/api/rss/content.rss"],
    "seldovia": ["https://www.seldovia.com/feed/"],
    "amsterdam": ["https://www.dutchnews.nl/feed/"],
    "brussels": ["https://www.thebulletin.be/rss.xml"],
    "stockholm": ["https://www.thelocal.se/rss"],
    "montreal": ["https://montrealgazette.com/feed/"],
    "vancouver": ["https://vancouversun.com/feed/"],
    "calgary": ["https://calgaryherald.com/feed/"],
    "ottawa": ["https://ottawacitizen.com/feed/"],
    "toronto": ["https://www.cp24.com/rss/cp24-news-rss-1.5859135"],
    "edmonton": ["https://edmontonjournal.com/feed/"],
    "winnipeg": ["https://winnipegsun.com/feed/"],
    "halifax": ["https://globalnews.ca/halifax/feed/"],
    "st johns": ["https://www.cbc.ca/cmlink/rss-canada-newfoundlandandlabrador"],
    "cape town": [
        "https://www.sowetanlive.co.za/rss/?publication=sowetan-live&section=news", 
        "https://www.iol.co.za/cmlink/1.640"
    ],
    "melbourne": ["https://www.abc.net.au/news/feed/2942460/rss.xml"],
    "auckland": ["https://www.nzherald.co.nz/news/rss.xml"],
    "perth": ["https://thewest.com.au/feed"],
    "brisbane": ["https://www.brisbanetimes.com.au/rss/feed.xml"],
    "mumbai": ["https://timesofindia.indiatimes.com/rssfeeds/-2128838597.cms"],
    "delhi": ["https://timesofindia.indiatimes.com/rssfeeds/-2128839596.cms"],
    "karachi": ["https://www.dawn.com/feeds/home"],
    "bangkok": ["https://www.bangkokpost.com/rss/data/topstories.xml"],
    "hanoi": ["https://vietnamnews.vn/rss"],
    "jakarta": ["https://www.thejakartapost.com/rss"],
    "kuala lumpur": ["https://www.nst.com.my/rss"],
    "tel aviv": ["https://www.jpost.com/rss/rssfeedsfrontpage.aspx"],
    "dubai": ["https://www.wam.ae/en/rss/feed/g4xnlor4yz?slug=english-rss-viewnull&vsCode=avs-002-1jc73h1izx3w&type=rss"],
    "nairobi": ["https://www.nation.co.ke/rss.xml"],
    "addis ababa": ["https://addisstandard.com/feed/"],
    "lagos": ["https://thenationonlineng.net/feed/"],
    "accra": ["https://www.ghanaweb.com/GhanaHomePage/NewsArchive/rss"],
    "riyadh": ["https://www.okaz.com.sa/rssFeed/1"],
    "baghdad": ["https://www.iraqinews.com/feed/"],
    "jeddah": ["https://english.alarabiya.net/tools/rss"],
    "doha": ["https://www.gulf-times.com/rss"],
    "kuwait city": ["https://www.arabtimesonline.com/news/rss/"],
}

# ---------------------- Country-level feeds (ENGLISH ONLY) ----------------------
# Only English-language country feeds or international sections
COUNTRY_FEEDS = {
    "angola": [
        "https://globalvoices.org/-/world/sub-saharan-africa/angola/feed/",
        "https://allafrica.com/tools/headlines/rdf/angola/headlines.rdf"
        ],
    "algeria": [
        "https://allafrica.com/tools/headlines/rdf/algeria/headlines.rdf",
        "https://globalvoices.org/-/world/middle-east-north-africa/algeria/feed/"
        ],    
    "austria": ["https://globalvoices.org/-/world/western-europe/austria/feed/"],
    "argentina": ["https://globalvoices.org/-/world/latin-america/argentina/feed/"],
    "afghanistan": ["https://globalvoices.org/-/world/central-asia-caucasus/afghanistan/feed/"],
    "cyprus": ["https://globalvoices.org/-/world/western-europe/cyprus/feed/"],
    "san marino": ["https://globalvoices.org/-/world/western-europe/san-marino/feed/"],
    "vatican city": ["https://globalvoices.org/-/world/western-europe/vatican-city/feed/"],
    "russia": ["https://globalvoices.org/-/world/eastern-central-europe/russia/feed/"],
    "china": ["https://globalvoices.org/-/world/east-asia/china/feed/"],
    "new zealand": ["https://globalvoices.org/-/world/oceania/new-zealand/feed/"],
    "papua new guinea": ["https://globalvoices.org/-/world/oceania/papua-new-guinea/feed/"],
    "united kingdom": [
        "https://feeds.bbci.co.uk/news/uk/rss.xml",
        "https://globalvoices.org/-/world/western-europe/united-kingdom/feed/"
        ],
    "turkey": [
        "https://globalvoices.org/-/world/middle-east-north-africa/turkey/feed/",
        "https://en.yenisafak.com/rss-feeds?category=turkiye",
        "https://www.mfa.gov.tr/en.rss.mfa?7342a8d1-3117-42aa-8ddd-01adb5653889"
        ],
    "germany": ["https://globalvoices.org/-/world/western-europe/germany/feed/"],
    "united states": [
        "https://rss.nytimes.com/services/xml/rss/nyt/US.xml",
        "https://globalvoices.org/-/world/north-america/usa/feed/"
        ],
    "canada": [
        "https://www.cbc.ca/cmlink/rss-canada",
        "https://globalvoices.org/-/world/north-america/canada/feed/"
        ],
    "australia": [
        "https://www.abc.net.au/news/feed/51120/rss.xml",
        "https://globalvoices.org/-/world/oceania/australia/feed/"
        ],
    "fiji": ["https://globalvoices.org/-/world/oceania/fiji/feed/"],
    "india": [
        "https://timesofindia.indiatimes.com/rssfeeds/-2128936835.cms",
        "https://globalvoices.org/-/world/south-asia/india/feed/"
        ],
    "south africa": [
        "https://www.news24.com/news24/rss",
        "https://allafrica.com/tools/headlines/rdf/southafrica/headlines.rdf",
        "https://globalvoices.org/-/world/sub-saharan-africa/south-africa/feed/"
                     ],
    "namibia" :[
        "https://globalvoices.org/-/world/sub-saharan-africa/namibia/feed/",
        "https://allafrica.com/tools/headlines/rdf/namibia/headlines.rdf"
        ],
    "pakistan": [
        "https://www.dawn.com/feeds/home",
        "https://globalvoices.org/-/world/south-asia/pakistan/feed/"
        ],
    "singapore": ["https://www.straitstimes.com/news/singapore/rss.xml"],
    "philippines": ["https://www.philstar.com/rss/nation"],
    "malaysia": [
        "https://www.nst.com.my/rss",
        "https://globalvoices.org/-/world/east-asia/malaysia/feed/"
                 ],
    "thailand": ["https://www.bangkokpost.com/rss/data/topstories.xml"],
    "vietnam": ["https://vietnamnews.vn/rss"],
    "indonesia": [
        "https://www.thejakartapost.com/rss",
        "https://globalvoices.org/-/world/east-asia/indonesia/feed/"
        ],   
    "kenya": [
        "https://www.nation.co.ke/rss.xml", 
        "https://globalvoices.org/-/world/sub-saharan-africa/kenya/feed/",
        "https://allafrica.com/tools/headlines/rdf/kenya/headlines.rdf"
        ],
    "rwanda": [
        "https://globalvoices.org/-/world/sub-saharan-africa/rwanda/feed/",
        "https://allafrica.com/tools/headlines/rdf/rwanda/headlines.rdf"
        ],
    "south sudan": [
        "https://globalvoices.org/-/world/sub-saharan-africa/south-sudan/feed/",
        "https://allafrica.com/tools/headlines/rdf/southsudan/headlines.rdf"
        ],
    "sudan": [
        "https://globalvoices.org/-/world/sub-saharan-africa/sudan/feed/",
        "https://allafrica.com/tools/headlines/rdf/sudan/headlines.rdf"
        ],
    "mali": [
        "https://globalvoices.org/-/world/sub-saharan-africa/mali/feed/",
        "https://allafrica.com/tools/headlines/rdf/mali/headlines.rdf"
        ],
    "republic of congo": ["https://globalvoices.org/-/world/sub-saharan-africa/republic-of-congo/feed/"],    
    "tunisia": [
        "https://allafrica.com/tools/headlines/rdf/tunisia/headlines.rdf",
        "https://globalvoices.org/-/world/middle-east-north-africa/tunisia/feed/"
        ],
    "nigeria": [
        "https://thenationonlineng.net/feed/",
        "https://newsblenda.com/feed/",
        "https://globalvoices.org/-/world/sub-saharan-africa/nigeria/feed/",
        "https://allafrica.com/tools/headlines/rdf/nigeria/headlines.rdf"
    ],
    "haiti": ["https://globalvoices.org/-/world/caribbean/haiti/feed/"],
    "panama": ["https://globalvoices.org/-/world/latin-america/panama/feed/"],
    "jamaica": ["https://globalvoices.org/-/world/caribbean/jamaica/feed/"],
    "suriname": ["https://globalvoices.org/-/world/caribbean/suriname/feed/"],
    "egypt": [
        "https://globalvoices.org/-/world/middle-east-north-africa/egypt/feed/",
        "https://allafrica.com/tools/headlines/rdf/egypt/headlines.rdf"
        ],
    "niger": [
        "https://globalvoices.org/-/world/sub-saharan-africa/niger/feed/",
        "https://allafrica.com/tools/headlines/rdf/niger/headlines.rdf"
        ],
    "benin": [
        "https://globalvoices.org/-/world/sub-saharan-africa/benin/feed/",
        "https://allafrica.com/tools/headlines/rdf/benin/headlines.rdf"
        ],
    "botswana": [
        "https://globalvoices.org/-/world/sub-saharan-africa/botswana/feed/",
        "https://allafrica.com/tools/headlines/rdf/botswana/headlines.rdf"
        ],
    "cameroon": [
        "https://globalvoices.org/-/world/sub-saharan-africa/cameroon/feed/",
        "https://allafrica.com/tools/headlines/rdf/cameroon/headlines.rdf"
        ],
    "chad": [
        "https://globalvoices.org/-/world/sub-saharan-africa/chad/feed/",
        "https://allafrica.com/tools/headlines/rdf/chad/headlines.rdf"
        ],
    "central african republic": [
        "https://globalvoices.org/-/world/sub-saharan-africa/central-african-republic/feed/",
        "https://allafrica.com/tools/headlines/rdf/centralafricanrepublic/headlines.rdf"
        ],
    "ghana": [
        "https://www.ghanaweb.com/GhanaHomePage/NewsArchive/rss",
        "https://globalvoices.org/-/world/sub-saharan-africa/ghana/feed/",
        "https://allafrica.com/tools/headlines/rdf/ghana/headlines.rdf"
        ],
    "sierra leone": [
        "https://globalvoices.org/-/world/sub-saharan-africa/sierra-leone/feed/",
        "https://allafrica.com/tools/headlines/rdf/sierraleone/headlines.rdf"
        ],
    "senegal": [
        "https://globalvoices.org/-/world/sub-saharan-africa/senegal/feed/",
        "https://allafrica.com/tools/headlines/rdf/senegal/headlines.rdf"
        ],    
    "ethiopia": [
        "https://addisstandard.com/feed/",
        "https://globalvoices.org/-/world/sub-saharan-africa/ethiopia/feed/",
        "https://allafrica.com/tools/headlines/rdf/ethiopia/headlines.rdf"
        ],
    "eritrea": [
        "https://allafrica.com/tools/headlines/rdf/eritrea/headlines.rdf",
        "https://globalvoices.org/-/world/sub-saharan-africa/eritrea/feed/"
        ],
    "gabon": [
        "https://globalvoices.org/-/world/sub-saharan-africa/gabon/feed/",
        "https://allafrica.com/tools/headlines/rdf/gabon/headlines.rdf"
        ],
    "gambia": [
        "https://globalvoices.org/-/world/sub-saharan-africa/gambia/feed/",
        "https://allafrica.com/tools/headlines/rdf/gambia/headlines.rdf"
        ],
    "ivory coast": [
        "https://globalvoices.org/-/world/sub-saharan-africa/cote-divoire/feed/",
        "https://allafrica.com/tools/headlines/rdf/cotedivoire/headlines.rdf"
        ],
    "uganda": [
        "https://www.watchdoguganda.com/feed",
        "https://globalvoices.org/-/world/sub-saharan-africa/uganda/feed/",
        "https://allafrica.com/tools/headlines/rdf/uganda/headlines.rdf"
        ],
    "djibouti": [
        "https://allafrica.com/tools/headlines/rdf/djibouti/headlines.rdf",
        "https://globalvoices.org/-/world/sub-saharan-africa/djibouti/feed/"
        ],
    "guinea": [
        "https://globalvoices.org/-/world/sub-saharan-africa/guinea/feed/",
        "https://allafrica.com/tools/headlines/rdf/guinea/headlines.rdf"
        ],
    "guniea-bissau": [
        "https://globalvoices.org/-/world/sub-saharan-africa/guinea-bissau/feed/",
        "https://allafrica.com/tools/headlines/rdf/guineabissau/headlines.rdf"
        ],
    "equatorial guinea": [
        "https://globalvoices.org/-/world/sub-saharan-africa/equatorial-guinea/feed/",
        "https://allafrica.com/tools/headlines/rdf/equatorialguinea/headlines.rdf"
        ],
    "burkina faso": [
        "https://globalvoices.org/-/world/sub-saharan-africa/burkina-faso/feed/",
        "https://allafrica.com/tools/headlines/rdf/burkinafaso/headlines.rdf"
        ],
    "burundi": [
        "https://globalvoices.org/-/world/sub-saharan-africa/burundi/feed/",
        "https://allafrica.com/tools/headlines/rdf/burundi/headlines.rdf"
        ],
    "tanzania": [
        "https://globalvoices.org/-/world/sub-saharan-africa/tanzania/feed/",
        "https://allafrica.com/tools/headlines/rdf/tanzania/headlines.rdf"
        ],    
    "liberia": [
        "https://allafrica.com/tools/headlines/rdf/liberia/headlines.rdf",
        "https://globalvoices.org/-/world/sub-saharan-africa/liberia/feed/"
        ],
    "zambia": [
        "https://allafrica.com/tools/headlines/rdf/zambia/headlines.rdf",
        "https://globalvoices.org/-/world/sub-saharan-africa/zambia/feed/"
    ],
    "zimbabwe": [
        "https://3-mob.com/feed/",
        "https://globalvoices.org/-/world/sub-saharan-africa/zimbabwe/feed/",
        "https://allafrica.com/tools/headlines/rdf/zimbabwe/headlines.rdf"
        ],
    "somalia": [
        "https://globalvoices.org/-/world/sub-saharan-africa/somalia/feed/",
        "https://allafrica.com/tools/headlines/rdf/somalia/headlines.rdf"
        ],
    "somaliland": ["https://globalvoices.org/-/world/sub-saharan-africa/somaliland/feed/"],
    "madagascar": [
        "https://allafrica.com/tools/headlines/rdf/madagascar/headlines.rdf",
        "https://globalvoices.org/-/world/sub-saharan-africa/madagascar/feed/"
        ],
    "mozambique": [
        "https://globalvoices.org/-/world/sub-saharan-africa/mozambique/feed/",
        "https://allafrica.com/tools/headlines/rdf/mozambique/headlines.rdf"
        ],
    "mauritania": [
        "https://allafrica.com/tools/headlines/rdf/mauritania/headlines.rdf",
        "https://globalvoices.org/-/world/sub-saharan-africa/mauritania/feed/"
        ],    
    "morocco": [
        "https://www.moroccoworldnews.com/feed",
        "https://www.moroccoworldnews.com/international/feed/",
        "https://allafrica.com/tools/headlines/rdf/morocco/headlines.rdf",
        "https://globalvoices.org/-/world/middle-east-north-africa/morocco/feed/"
    ],
    "libya": [
        "https://globalvoices.org/-/world/middle-east-north-africa/libya/feed/",
        "https://allafrica.com/tools/headlines/rdf/libya/headlines.rdf"
        ],
    "iran": [
        "https://globalvoices.org/-/world/middle-east-north-africa/iran/feed/",
        "https://www.jpost.com/rss/rssfeedsiran"
        ],
    "jordan": ["https://globalvoices.org/-/world/middle-east-north-africa/jordan/feed/"],
    "lebanon": ["https://globalvoices.org/-/world/middle-east-north-africa/lebanon/feed/"],
    "israel": [
        "https://www.jpost.com/rss/rssfeedsisraelnews.aspx",
        "https://globalvoices.org/-/world/middle-east-north-africa/israel/feed/"
        ],
    "iraq": [
        "https://www.iraqinews.com/feed/",
        "https://globalvoices.org/-/world/middle-east-north-africa/iraq/feed/"
        ],
    "uae": [
        "https://gulfnews.com/rss/1.454509",
        "https://globalvoices.org/-/world/middle-east-north-africa/united-arab-emirates/feed/"
        ],
    "qatar": [
        "https://www.gulf-times.com/rss",
        "https://globalvoices.org/-/world/middle-east-north-africa/qatar/feed/"
        ],
    "kuwait": [
        "https://www.arabtimesonline.com/news/rss/",
        "https://globalvoices.org/-/world/middle-east-north-africa/kuwait/feed/"
        ],
    "oman": ["https://globalvoices.org/-/world/middle-east-north-africa/oman/feed/"],
    "saudi arabia": [
        "https://english.alarabiya.net/feed/rss2/en/in-translation.xml",
        "https://globalvoices.org/-/world/middle-east-north-africa/saudi-arabia/feed/"
        ],
    "belgium": [
        "https://www.brusselstimes.com/feed",
        "https://globalvoices.org/-/world/western-europe/belgium/feed/"
        ],
    "italy": ["https://globalvoices.org/-/world/western-europe/italy/feed/"],
    "france": ["https://globalvoices.org/-/world/western-europe/france/feed/"],
    "spain": ["https://globalvoices.org/-/world/western-europe/spain/feed/"],
    "switzerland": ["https://globalvoices.org/-/world/western-europe/switzerland/feed/"],
    "malta": ["https://globalvoices.org/-/world/western-europe/malta/feed/"],
    "monaco": ["https://globalvoices.org/-/world/western-europe/monaco/feed/"],
    "norway": ["https://globalvoices.org/-/world/western-europe/norway/feed/"],
    "iceland": ["https://globalvoices.org/-/world/western-europe/iceland/feed/"],
    "denmark": ["https://globalvoices.org/-/world/western-europe/denmark/feed/"],
    "finland": ["https://globalvoices.org/-/world/western-europe/finland/feed/"],
    "netherlands": [
        "https://www.dutchnews.nl/feed/",
        "https://globalvoices.org/-/world/western-europe/netherlands/feed/"
        ],
    "sweden": [
        "https://www.thelocal.se/rss",
        "https://globalvoices.org/-/world/western-europe/sweden/feed/"
        ],
    "czech republic": [
        "https://english.radio.cz/rss",
        "https://globalvoices.org/-/world/eastern-central-europe/czech-republic/feed/"
        ],
    "hungary": [
        "https://dailynewshungary.com/feed/",
        "https://globalvoices.org/-/world/eastern-central-europe/hungary/feed/"
        ],
    "poland": [
        "https://www.thefirstnews.com/rss",
        "https://globalvoices.org/-/world/eastern-central-europe/poland/feed/"
        ],
    "romania": [
        "https://www.romania-insider.com/rss",
        "https://globalvoices.org/-/world/eastern-central-europe/romania/feed/"
        ],
    "greece": [
        "https://www.ekathimerini.com/rss",
        "https://globalvoices.org/-/world/western-europe/greece/feed/"
        ],
    "ukraine": [
        "https://www.kyivpost.com/feed",
        "https://globalvoices.org/-/world/eastern-central-europe/ukraine/feed/"
        ],
    "serbia": [
        "https://balkaninsight.com/category/bi/serbia/",
        "https://globalvoices.org/-/world/eastern-central-europe/serbia/feed/"
        ],
    "slovakia": ["https://globalvoices.org/-/world/eastern-central-europe/slovakia/feed/"],    
    "slovenia": ["https://globalvoices.org/-/world/eastern-central-europe/slovenia/feed/"],
    "montenegro": [
        "https://balkaninsight.com/category/bi/montenegro/",
        "https://globalvoices.org/-/world/eastern-central-europe/montenegro/feed/"
        ],
    "bosnia and herzegovina": [
        "https://balkaninsight.com/category/bi/bosnia-and-herzegovina/",
        "https://globalvoices.org/-/world/eastern-central-europe/bosnia-herzegovina/feed/"
        ],
    "kosovo": [
        "https://balkaninsight.com/category/bi/kosovo/",
        "https://globalvoices.org/-/world/eastern-central-europe/kosovo/feed/"
        ],
    "western sahara": [
        "https://globalvoices.org/-/world/middle-east-north-africa/western-sahara/feed/",
        "https://allafrica.com/tools/headlines/rdf/westernsahara/headlines.rdf"
        ],    
    "north macedonia": [
        "https://balkaninsight.com/category/bi/macedonia/",
        "https://globalvoices.org/-/world/eastern-central-europe/macedonia/feed/"
        ],
    "croatia": [
        "https://balkaninsight.com/category/bi/croatia/",
        "https://globalvoices.org/-/world/eastern-central-europe/croatia/feed/"
        ],
    "albania": [
        "https://balkaninsight.com/category/bi/albania/",
        "https://globalvoices.org/-/world/eastern-central-europe/albania/feed/"
        ],
    "bulgaria": [
        "https://balkaninsight.com/category/bi/bulgaria/",
        "https://globalvoices.org/-/world/eastern-central-europe/bulgaria/feed/"
        ],
    "moldova": [
        "https://balkaninsight.com/category/bi/moldova/",
        "https://globalvoices.org/-/world/eastern-central-europe/moldova/feed/"
        ],
    "portugal": ["https://globalvoices.org/-/world/western-europe/portugal/feed/"],
    "ireland": ["https://globalvoices.org/-/world/western-europe/ireland/feed/"],    
    "uruguay": ["https://globalvoices.org/-/world/latin-america/uruguay/feed/"],
    "paraguay": ["https://globalvoices.org/-/world/latin-america/paraguay/feed/"],
    "mexico": ["https://globalvoices.org/-/world/latin-america/mexico/feed/"],
    "colombia": ["https://globalvoices.org/-/world/latin-america/colombia/feed/"],
    "venezuela": ["https://globalvoices.org/-/world/latin-america/venezuela/feed/"],
    "yemen": ["https://globalvoices.org/-/world/middle-east-north-africa/yemen/feed/"],
    "japan": ["https://globalvoices.org/-/world/east-asia/japan/feed/"],
}

# ---------------------- Global feeds (PRIMARY SOURCE) ----------------------
# These are now your PRIMARY intelligence source - not fallback
# Global English feeds with keyword + location extraction
# Location detection happens via content analysis
GLOBAL_FEEDS = [
    # Cyber security & infrastructure (critical for threat intel)
    "https://www.cisa.gov/news.xml",
    "https://www.darkreading.com/rss.xml",
    "https://krebsonsecurity.com/feed/",
    "https://www.bleepingcomputer.com/feed/",
    "https://www.securitymagazine.com/rss/",
    "https://feeds.feedburner.com/TheHackersNews",
    "https://www.csoonline.com/feed/",
    "https://intel471.com/blog/feed",
    
    # Major global news networks (comprehensive coverage)
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/Africa.xml",
    "https://allafrica.com/tools/headlines/rdf/africa/headlines.rdf",
    "https://rss.nytimes.com/services/xml/rss/nyt/Americas.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/AsiaPacific.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/Europe.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/MiddleEast.xml",
    # United Nations global/region/topic feeds
    "https://news.un.org/feed/subscribe/en/news/region/global/feed/rss.xml",
    "https://news.un.org/feed/subscribe/en/news/region/middle-east/feed/rss.xml",
    "https://news.un.org/feed/subscribe/en/news/region/africa/feed/rss.xml",
    "https://news.un.org/feed/subscribe/en/news/region/europe/feed/rss.xml",
    "https://news.un.org/feed/subscribe/en/news/region/americas/feed/rss.xml",
    "https://news.un.org/feed/subscribe/en/news/region/asia-pacific/feed/rss.xml",
    "https://news.un.org/feed/subscribe/en/news/topic/peace-and-security/feed/rss.xml",
    "https://news.un.org/feed/subscribe/en/news/topic/health/feed/rss.xml",
    # Major global news networks
    "https://www.cbsnews.com/latest/rss/world",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://abcnews.go.com/abcnews/internationalheadlines",
    "https://www.cnbc.com/id/100727362/device/rss/rss.html",
    "https://feeds.nbcnews.com/nbcnews/public/news",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://globalnews.ca/world/feed/",
    "https://feeds.washingtonpost.com/rss/world",
    "https://feeds.feedburner.com/time/world",
    "https://www.washingtontimes.com/rss/headlines/news/world",
    "https://www.smh.com.au/rss/world.xml",
    "https://feeds.npr.org/1004/rss.xml",
    "https://feeds.skynews.com/feeds/rss/world.xml",
    "https://www.latimes.com/world-nation/rss2.0.xml",
    "https://timesofindia.indiatimes.com/rssfeeds/296589292.cms",
    "https://www.rt.com/rss/news/",
    "https://feeds.feedburner.com/ndtvnews-world-news",
    "https://www.thesun.co.uk/news/worldnews/feed/",
    "https://www.globalissues.org/news/feed",
    "https://www.mirror.co.uk/news/world-news/?service=rss",
    "https://feeds.feedburner.com/daily-express-world-news",
    "https://www.vox.com/rss/world-politics/index.xml",
    "https://www1.cbn.com/app_feeds/rss/news/rss.php?section=world&mobile=false&q=cbnnews/world/feed",
    "https://www.scmp.com/rss/91/feed/",
    "https://www.independent.co.uk/news/world/rss",
    "https://feeds.breakingnews.ie/bnworld",
    "https://www.spiegel.de/international/index.rss",
    "https://www.theguardian.com/world/rss",
    "https://www.rfi.fr/en/international/rss",
    "https://www.sbs.com.au/news/topic/world/feed",
    "https://www.scrippsnews.com/world.rss",
    "https://www.chicagotribune.com/news/world/feed/",
    "https://news.google.com/atom/topics/CAAqKggKIiRDQkFTRlFvSUwyMHZNRGx1YlY4U0JXVnVMVWRDR2dKSlRpZ0FQAQ?hl=en-IN&gl=IN&ceid=IN:en&oc=11",
    "https://asiatimes.com/category/world/feed/",
    "https://www.jpost.com/rss/rssfeedsheadlines.aspx",
    "https://asiatimes.com/feed/",
    # Security, defense, geopolitical intelligence
    "https://www.thecipherbrief.com/feeds/feed.rss",
    "https://warontherocks.com/feed/",
    "https://www.jpost.com/rss/israel-hamas-war",
    "https://www.jpost.com/rss/rssfeedsislamicterrorism",
    "https://allafrica.com/tools/headlines/rdf/corruption/headlines.rdf",
    "https://allafrica.com/tools/headlines/rdf/ebola/headlines.rdf",
    "https://allafrica.com/tools/headlines/rdf/terrorism/headlines.rdf",
    "https://allafrica.com/tools/headlines/rdf/conflict/headlines.rdf",
    "https://allafrica.com/tools/headlines/rdf/health/headlines.rdf",
    "https://allafrica.com/tools/headlines/rdf/aids/headlines.rdf",
    "https://defence-blog.com/feed/",
    "https://www.dailysabah.com/rss/world/syrian-crisis",
    "https://www.dailysabah.com/rss/world/islamophobia",
    "https://www.dailysabah.com/rss/politics/war-on-terror",
    "https://www.rand.org/topics/international-affairs.xml/feed",
    "https://feeds.feedburner.com/WarNewsUpdates",
    "https://asiandefencenewschannel.blogspot.com/feeds/posts/default",
    # Independent/underreported regions
    "https://globalpressjournal.com/feed/",
    "https://www.usnn.news/feed/",
    "https://www.jpost.com/rss/rssfeedsgaza.aspx",
    "https://www.jpost.com/rss/rssfeedsarabisraeliconflict.aspx",
    "https://worldunitednews.blogspot.com/feeds/posts/default",
    "https://ifpnews.com/feed/",
    "https://easternherald.com/feed/",
    "https://wowplus.net/feed/",
    "https://internetprotocol.co/rss/",
    "https://rocetoday.com/feed/",
    # Government advisories and global disaster alerts
    "https://www.gov.uk/foreign-travel-advice.atom",
    "https://travel.state.gov/_res/rss/TAsTWs.xml",
    "https://www.smartraveller.gov.au/countries/documents/do-not-travel.rss",
    "https://www.smartraveller.gov.au/countries/documents/reconsider-your-need-to-travel.rss",
    "https://www.gdacs.org/xml/rss_24h.xml",
    "https://www.emro.who.int/index.php?option=com_mediarss&feed_id=3&format=raw",
]