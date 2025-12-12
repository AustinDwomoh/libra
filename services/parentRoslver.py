from dataclasses import dataclass
from typing import Optional, List
from collections import Counter
import requests
from services.config import Config
import logging

logger = logging.getLogger(__name__)


@dataclass
class ParentResolution:
    raw_name: str
    parent_brand: Optional[str]
    parent_domain: Optional[str]
    confidence: float
    evidence: List[str]

class ParentBrandResolver:
    ROLE_TERMS = {
        "associate",
        "associates",
        "employee",
        "employees",
        "careers",
        "jobs",
        "working at",
    }

    def __init__(self):
        self.api_key = Config.GOOGLE_API_KEY
        self.cx = Config.GOOGLE_CX
        self.endpoint = "https://www.googleapis.com/customsearch/v1"
        self.cache = {}

    # --------------------------------------------------
    # Google PSE query
    # --------------------------------------------------
    def _search(self, query: str) -> dict:
        params = {
            "key": self.api_key,
            "cx": self.cx,
            "q": query,
        }
        resp = requests.get(self.endpoint, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    # --------------------------------------------------
    # Signal extraction
    # --------------------------------------------------
    def _extract_signals(self, data: dict) -> dict:
        domains, snippets = [], []

        for item in data.get("items", [])[:5]:
            domains.append(item.get("displayLink", "").lower())
            snippets.append(item.get("snippet", "").lower())

        return {
            "domains": domains,
            "snippets": snippets,
        }

    # --------------------------------------------------
    # Domain consensus → brand
    # --------------------------------------------------
    def _dominant_brand(self, domains: List[str]) -> Optional[tuple[str, str]]:
        roots = []
        domain_map = {}

        for d in domains:
            parts = d.split(".")
            if len(parts) >= 2:
                root = parts[-2]
                roots.append(root)
                domain_map.setdefault(root, []).append(d)

        if not roots:
            return None

        brand, freq = Counter(roots).most_common(1)[0]

        if freq < 3:
            return None

        canonical_domain = Counter(domain_map[brand]).most_common(1)[0][0]

        if len(brand) <= 4:
            brand_name = brand.upper()
        else:
            brand_name = brand.capitalize()

        return brand_name, canonical_domain                                                          


    # --------------------------------------------------
    # Role language boost
    # --------------------------------------------------
    def _role_language_score(self, snippets: List[str]) -> float:
        if not snippets:
            return 0.0

        hits = 0
        for s in snippets:
            if any(term in s for term in self.ROLE_TERMS):
                hits += 1

        return hits / len(snippets)

    # --------------------------------------------------
    # Public API
    # --------------------------------------------------
    def resolve(self, raw_name: str) -> ParentResolution:
        
        cache_key = raw_name.lower().strip()
        if cache_key in self.cache:
            return self.cache[cache_key]
    
        try:
            data = self._search(raw_name)
        except Exception as e:
            logger.warning(f"PSE lookup failed for '{raw_name}': {e}")
            result = ParentResolution(
                raw_name=raw_name,
                parent_brand=None,
                parent_domain=None,
                confidence=0.0,
                evidence=["pse_error"],
            )
            self.cache[cache_key] = result
            return result
    
        if not data.get("items"):
            result = ParentResolution(
                raw_name=raw_name,
                parent_brand=None,
                parent_domain=None,
                confidence=0.0,
                evidence=["no_results"],
            )
            self.cache[cache_key] = result
            return result
    
        signals = self._extract_signals(data)
        result_pair = self._dominant_brand(signals["domains"])
    
        parent = None
        domain = None
        confidence = 0.0
        evidence = []
    
        if result_pair:
            parent, domain = result_pair
            confidence = 0.7
            evidence.append("google_pse_domain_consensus")
    
            role_score = self._role_language_score(signals["snippets"])
            if role_score > 0:
                confidence += 0.2 * role_score
                evidence.append("role_language_detected")
    
        confidence = min(confidence, 0.95)
    
        result = ParentResolution(
            raw_name=raw_name,
            parent_brand=parent,
            parent_domain=domain,
            confidence=confidence,
            evidence=evidence,
        )
    
        self.cache[cache_key] = result
        return result
    