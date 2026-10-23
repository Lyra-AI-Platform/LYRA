"""What the newswire collects and how it tags it. Edit freely: everything here is data."""

# GDELT topic queries: every language and country GDELT monitors (100+ languages, every 15
# minutes). GDELT rejects words under three letters, so "AI" is spelled out.
GDELT_TOPICS = {
    "markets": '(stocks OR "stock market" OR earnings OR "bond yields" OR "share price" OR "market sell-off")',
    "central-banks": '("central bank" OR "interest rates" OR inflation OR "Federal Reserve" OR ECB OR "Bank of England" OR "Bank of Japan")',
    "ai": '("artificial intelligence" OR OpenAI OR Anthropic OR "DeepMind" OR "large language model" OR "machine learning" OR "generative")',
    "semiconductors": '(semiconductor OR chipmaker OR TSMC OR ASML OR Nvidia OR "chip export")',
    "chemicals": '(chemical OR chemicals OR petrochemical OR BASF OR "Dow Inc" OR LyondellBasell OR fertilizer OR polymer)',
    "pharma": '(pharmaceutical OR "drug trial" OR "clinical trial" OR FDA OR vaccine OR biotech)',
    "energy": '(oil OR "natural gas" OR OPEC OR LNG OR "renewable energy" OR refinery OR "power grid")',
    "politics": '(election OR parliament OR congress OR senate OR "prime minister" OR president OR minister)',
    "trade-policy": '(tariff OR tariffs OR sanctions OR "trade deal" OR "export controls" OR "trade war")',
    "regulation": '(regulator OR regulation OR antitrust OR "competition authority" OR "SEC charges" OR lawsuit)',
    "defence": '(defence OR defense OR military OR NATO OR "arms deal" OR missile)',
    "climate": '(climate OR emissions OR "carbon price" OR "net zero" OR drought OR wildfire)',
    "crypto": '(bitcoin OR crypto OR stablecoin OR ethereum OR "digital currency")',
    "mergers": '(merger OR acquisition OR takeover OR "buyout" OR IPO OR "stake in")',
    "labour": '(strike OR layoffs OR "job cuts" OR unemployment OR wages)',
    "supply-chain": '(shortage OR "supply chain" OR shipping OR "Suez" OR "Red Sea" OR "port strike")',
}

# Country sweeps: business and policy news published in each country, in its own languages.
# Two-letter GDELT/FIPS source-country codes, mapped to ISO for display.
GDELT_COUNTRIES = {
    "US": "US", "UK": "GB", "CA": "CA", "AS": "AU", "IN": "IN", "CH": "CN", "JA": "JP", "KS": "KR", "TW": "TW",
    "GM": "DE", "FR": "FR", "IT": "IT", "SP": "ES", "NL": "NL", "SZ": "CH", "SW": "SE", "BR": "BR", "MX": "MX",
    "AR": "AR", "SF": "ZA", "NI": "NG", "EG": "EG", "SA": "SA", "AE": "AE", "TU": "TR", "IS": "IL", "RS": "RU",
    "UP": "UA", "PL": "PL", "ID": "ID", "SN": "SG", "MY": "MY", "VM": "VN", "PH": "PH", "TH": "TH", "PK": "PK",
}
COUNTRY_QUERY = '(economy OR market OR government OR company OR minister OR exports)'

# Publishers' own feeds, with the country they report from.
RSS_FEEDS = [
    ("https://feeds.bbci.co.uk/news/world/rss.xml", "GB", "en"),
    ("https://feeds.bbci.co.uk/news/business/rss.xml", "GB", "en"),
    ("https://feeds.bbci.co.uk/news/technology/rss.xml", "GB", "en"),
    ("https://www.theguardian.com/world/rss", "GB", "en"),
    ("https://www.theguardian.com/business/rss", "GB", "en"),
    ("https://www.aljazeera.com/xml/rss/all.xml", "QA", "en"),
    ("https://rss.dw.com/rdf/rss-en-all", "DE", "en"),
    ("https://rss.dw.com/rdf/rss-en-bus", "DE", "en"),
    ("https://www.france24.com/en/rss", "FR", "en"),
    ("https://www.abc.net.au/news/feed/51120/rss.xml", "AU", "en"),
    ("https://www.cbc.ca/webfeed/rss/rss-world", "CA", "en"),
    ("https://www.cbc.ca/webfeed/rss/rss-business", "CA", "en"),
    ("https://timesofindia.indiatimes.com/rssfeedstopstories.cms", "IN", "en"),
    ("https://www.thehindu.com/business/feeder/default.rss", "IN", "en"),
    ("https://www.scmp.com/rss/91/feed", "HK", "en"),
    ("https://www3.nhk.or.jp/rss/news/cat0.xml", "JP", "ja"),
    ("https://feeds.npr.org/1001/rss.xml", "US", "en"),
    ("https://feeds.npr.org/1006/rss.xml", "US", "en"),
    ("https://www.cnbc.com/id/100003114/device/rss/rss.html", "US", "en"),
    ("https://www.cnbc.com/id/10000664/device/rss/rss.html", "US", "en"),
    ("https://feeds.content.dowjones.io/public/rss/mw_topstories", "US", "en"),
    ("https://www.technologyreview.com/feed/", "US", "en"),
    ("https://techcrunch.com/category/artificial-intelligence/feed/", "US", "en"),
    ("https://www.chemistryworld.com/rss", "GB", "en"),
    ("https://cen.acs.org/content/cen/rss.xml", "US", "en"),
    ("https://www.fiercepharma.com/rss/xml", "US", "en"),
    ("https://oilprice.com/rss/main", "US", "en"),
    ("https://www.politico.eu/feed/", "BE", "en"),
    ("https://www.politico.com/rss/politicopicks.xml", "US", "en"),
    ("https://www.lemonde.fr/rss/une.xml", "FR", "fr"),
    ("https://www.spiegel.de/schlagzeilen/index.rss", "DE", "de"),
    ("https://elpais.com/rss/elpais/portada.xml", "ES", "es"),
    ("https://www.ansa.it/sito/ansait_rss.xml", "IT", "it"),
    ("https://g1.globo.com/rss/g1/", "BR", "pt"),
]
# Google News front pages per edition (country, language).
GOOGLE_EDITIONS = [("US", "en"), ("GB", "en"), ("IN", "en"), ("AU", "en"), ("CA", "en"), ("SG", "en"), ("ZA", "en"),
                   ("NG", "en"), ("IE", "en"), ("DE", "de"), ("FR", "fr"), ("ES", "es"), ("IT", "it"), ("BR", "pt"),
                   ("MX", "es"), ("JP", "ja"), ("KR", "ko"), ("NL", "nl"), ("SE", "sv"), ("PL", "pl"), ("TR", "tr")]
GOOGLE_EDITION = "https://news.google.com/rss?hl={hl}&gl={gl}&ceid={gl}:{lang}"
GOOGLE_TOPIC = "https://news.google.com/rss/headlines/section/topic/{topic}?hl={hl}&gl={gl}&ceid={gl}:{lang}"

# New research. arXiv: AI, ML, NLP, chemistry, materials, biomolecules, quantitative finance.
ARXIV = ("https://export.arxiv.org/api/query?search_query={q}&sortBy=submittedDate&sortOrder=descending"
         "&start=0&max_results=200")
ARXIV_CATEGORIES = {
    "ai": ["cs.AI", "cs.LG", "cs.CL", "cs.CV", "stat.ML"],
    "chemicals": ["physics.chem-ph", "cond-mat.mtrl-sci", "cond-mat.soft"],
    "pharma": ["q-bio.BM", "q-bio.QM"],
    "markets": ["q-fin.ST", "q-fin.TR", "q-fin.CP"],
    "energy": ["physics.app-ph"],
}
# OpenAlex: every journal and preprint server (Crossref, PubMed, chemRxiv, bioRxiv...).
OPENALEX = ("https://api.openalex.org/works?search={q}&filter=from_publication_date:{since},type:article"
            "&sort=publication_date:desc&per-page=100&mailto=support@lyraauth.com"
            "&select=id,doi,title,publication_date,primary_location,authorships,language")
OPENALEX_SEARCHES = {
    "chemicals": ["catalyst", "polymer", "battery electrolyte", "petrochemical", "green hydrogen", "PFAS", "fertilizer",
                  "chemical recycling", "solvent", "semiconductor materials"],
    "pharma": ["drug discovery", "clinical trial results", "antibody", "GLP-1", "vaccine"],
    "ai": ["large language model", "machine learning chemistry", "deep learning"],
    "energy": ["lithium", "solar cell", "carbon capture", "nuclear fusion"],
}

# Topic words for tagging anything (RSS items, research) that didn't arrive with a topic.
TOPIC_WORDS = {
    "ai": ["artificial intelligence", " ai ", "openai", "anthropic", "chatgpt", "llm", "machine learning", "neural network", "deepmind", "gemini", "claude"],
    "semiconductors": ["semiconductor", "chipmaker", "tsmc", "asml", "nvidia", "wafer", "foundry"],
    "chemicals": ["chemical", "petrochemical", "polymer", "catalyst", "basf", "dow inc", "lyondellbasell", "fertilizer", "pfas", "solvent", "ethylene"],
    "pharma": ["pharma", "drug", "clinical trial", "fda", "vaccine", "biotech", "antibody"],
    "energy": ["oil", "natural gas", "opec", "lng", "renewable", "solar", "wind farm", "refinery", "nuclear"],
    "politics": ["election", "parliament", "congress", "senate", "prime minister", "president", "minister", "lawmakers"],
    "trade-policy": ["tariff", "sanction", "trade deal", "export control", "trade war"],
    "central-banks": ["central bank", "interest rate", "inflation", "federal reserve", "ecb", "bank of england"],
    "markets": ["stocks", "stock market", "shares", "earnings", "nasdaq", "s&p 500", "ftse", "dow jones", "bond"],
    "crypto": ["bitcoin", "crypto", "ethereum", "stablecoin"],
    "climate": ["climate", "emissions", "net zero", "carbon"],
    "defence": ["defence", "defense", "military", "nato", "missile"],
    "mergers": ["merger", "acquisition", "takeover", "buyout", "ipo"],
}

# Companies named in headlines, for linking articles to Tremor tickers. Chemical, AI, chip,
# pharma and energy names lead, since research and policy news moves them first.
COMPANIES = {
    "BASF": "BASFY", "Dow Inc": "DOW", "Dow Chemical": "DOW", "DuPont": "DD", "LyondellBasell": "LYB", "Linde": "LIN",
    "Air Products": "APD", "Albemarle": "ALB", "Eastman Chemical": "EMN", "Celanese": "CE", "Huntsman": "HUN",
    "Olin": "OLN", "Westlake": "WLK", "Mosaic": "MOS", "CF Industries": "CF", "Nutrien": "NTR", "Corteva": "CTVA",
    "FMC Corp": "FMC", "PPG": "PPG", "Sherwin-Williams": "SHW", "Ecolab": "ECL", "International Flavors": "IFF",
    "Chemours": "CC", "Covestro": "COV", "Bayer": "BAYRY", "Evonik": "EVKIY", "Solvay": "SOLVY", "AkzoNobel": "AKZOY",
    "Sika": "SXYAY", "Arkema": "ARKAY", "Wacker": "WCH", "Croda": "COIHY", "Johnson Matthey": "JMPLY", "Clariant": "CLZNY",
    "Nvidia": "NVDA", "AMD": "AMD", "Intel": "INTC", "TSMC": "TSM", "ASML": "ASML", "Broadcom": "AVGO", "Qualcomm": "QCOM",
    "Micron": "MU", "Arm Holdings": "ARM", "Samsung": "SSNLF", "SK Hynix": "HXSCL", "Applied Materials": "AMAT",
    "Microsoft": "MSFT", "Alphabet": "GOOGL", "Google": "GOOGL", "Amazon": "AMZN", "Meta": "META", "Apple": "AAPL",
    "Tesla": "TSLA", "Oracle": "ORCL", "Salesforce": "CRM", "IBM": "IBM", "Palantir": "PLTR", "Adobe": "ADBE",
    "Pfizer": "PFE", "Moderna": "MRNA", "Eli Lilly": "LLY", "Novo Nordisk": "NVO", "Merck": "MRK", "AstraZeneca": "AZN",
    "Johnson & Johnson": "JNJ", "AbbVie": "ABBV", "Roche": "RHHBY", "Novartis": "NVS", "Sanofi": "SNY", "GSK": "GSK",
    "Bristol Myers": "BMY", "Amgen": "AMGN", "Gilead": "GILD", "Regeneron": "REGN", "Vertex": "VRTX", "Biogen": "BIIB",
    "ExxonMobil": "XOM", "Exxon": "XOM", "Chevron": "CVX", "Shell": "SHEL", "BP": "BP", "TotalEnergies": "TTE",
    "ConocoPhillips": "COP", "Saudi Aramco": "2222.SR", "Occidental": "OXY", "Schlumberger": "SLB", "Equinor": "EQNR",
    "JPMorgan": "JPM", "Goldman Sachs": "GS", "Morgan Stanley": "MS", "BlackRock": "BLK", "Berkshire Hathaway": "BRK-B",
    "Boeing": "BA", "Airbus": "EADSY", "Lockheed Martin": "LMT", "Raytheon": "RTX", "Northrop": "NOC",
    "Walmart": "WMT", "Netflix": "NFLX", "Uber": "UBER", "Coinbase": "COIN", "MicroStrategy": "MSTR",
}
