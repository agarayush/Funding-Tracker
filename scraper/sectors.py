"""Fixed sector taxonomy plus a keyword classifier used when no API key is set."""
import re

SECTORS = {
    "Fintech": r"fintech|payment|lending|loan|credit|neobank|insurtech|insurance|wealth|invest(ing|ment) app|upi|nbfc|stock|trading|crypto|web3|blockchain|bank",
    "AI & Deeptech": r"\bai\b|artificial intelligence|machine learning|\bllm|genai|generative|deep ?tech|robotic|semiconductor|chip|quantum|computer vision|drone|autonomous|space ?tech|satellite",
    "SaaS & Enterprise Tech": r"saas|b2b software|enterprise|crm|erp|workflow|cybersecurity|security platform|devops|developer|cloud|api|hr ?tech|martech|sales platform|analytics platform",
    "D2C & Consumer Brands": r"d2c|direct-to-consumer|brand|apparel|fashion|beauty|skincare|cosmetic|personal care|jewel|footwear|snack|beverage|food brand|nutrition|pet ?care|petfood",
    "E-commerce & Quick Commerce": r"e-?commerce|marketplace|quick commerce|q-?commerce|social commerce|reseller|online store|retail tech",
    "Healthtech & Biotech": r"health|medical|medtech|hospital|clinic|diagnostic|pharma|biotech|genomic|wellness|mental health|fitness|telemedicine|elder ?care",
    "Edtech": r"edtech|education|learning|upskill|school|student|tutor|exam|test prep|course",
    "Climate & Cleantech": r"climate|clean ?tech|solar|renewable|\bev\b|electric vehicle|battery|charging|carbon|sustainab|recycl|waste|green hydrogen|energy",
    "Mobility & Automotive": r"mobility|automotive|vehicle|ride|fleet|two-wheeler|car |bike|transport",
    "Logistics & Supply Chain": r"logistic|supply chain|warehous|freight|shipping|delivery|last-mile|trucking|cold chain",
    "Agritech & Foodtech": r"agri|farm|crop|dairy|fisher|food ?tech|cloud kitchen|restaurant|grocery|fresh produce",
    "Media, Gaming & Content": r"gaming|game|esports|media|content|creator|ott|streaming|music|entertainment|social media|community app|trivia|puzzle|dating",
    "Real Estate & Proptech": r"real estate|proptech|property|housing|rental|co-?living|co-?working|construction|interior|home decor",
    "Manufacturing & Industrial": r"manufactur|industrial|factory|defen[cs]e|aerospace|electronics|hardware|textile|chemical|packaging|machinery",
    "Travel & Hospitality": r"travel|hospitality|hotel|tourism|booking|trip",
    "HR & Workforce": r"recruit|hiring|staffing|talent|payroll|gig work|blue-collar|jobs platform",
    "Other": r"$^",
}

ROUNDS = [
    "Pre-Seed", "Seed", "Pre-Series A", "Series A", "Pre-Series B", "Series B", "Pre-Series C", "Series C", "Series D",
    "Series E+", "Bridge", "Debt", "Grant", "Strategic", "Undisclosed",
]

_COMPILED = {k: re.compile(r"\b(?:" + v + ")", re.I) for k, v in SECTORS.items()}


def classify(text):
    """Pick the sector whose keywords appear most often in `text`."""
    scores = {k: len(rx.findall(text)) for k, rx in _COMPILED.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else "Other"


def normalize_round(text):
    t = (text or "").lower()
    if "pre-seed" in t or "pre seed" in t or "angel round" in t:
        return "Pre-Seed"
    m = re.search(r"pre[- ]series[- ]?([abc])\b", t)
    if m:
        return f"Pre-Series {m.group(1).upper()}"
    m = re.search(r"series[- ]([a-h])\b", t)
    if m:
        letter = m.group(1).upper()
        return f"Series {letter}" if letter in "ABCD" else "Series E+"
    if "seed" in t:
        return "Seed"
    if "bridge" in t:
        return "Bridge"
    if "debt" in t or "ncd" in t or "venture debt" in t:
        return "Debt"
    if "grant" in t:
        return "Grant"
    if "strategic" in t:
        return "Strategic"
    return "Undisclosed"
