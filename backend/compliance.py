"""Compliance rules engine for e-commerce products.

Evaluates a product (attributes + market) against a catalog of real
regulations: CE marking (EU), FCC (US), RoHS, REACH, GPSR, Prop 65,
CPSIA, UKCA, CA/EU battery regs, etc.

Each rule produces findings with a severity; the engine aggregates them
into per-regulation status + an overall compliance score (0-100).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# Finding / regulation types
# --------------------------------------------------------------------------
SEV_BLOCKER = "blocker"
SEV_WARNING = "warning"
SEV_INFO = "info"
SEV_OK = "ok"

STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_REVIEW = "review"
STATUS_NA = "not_applicable"

SEVERITY_ORDER = {SEV_BLOCKER: 0, SEV_WARNING: 1, SEV_INFO: 2, SEV_OK: 3}


@dataclass
class Finding:
    severity: str
    title: str
    detail: str = ""
    evidence_required: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "evidence_required": self.evidence_required,
        }


@dataclass
class RegulationResult:
    code: str
    name: str
    markets: list[str]
    status: str
    severity: str
    score: int  # 0-100 for this regulation
    findings: list[dict] = field(default_factory=list)


class Regulation:
    def __init__(self, code: str, name: str, markets: list[str], applies_to: list[str],
                 description: str = ""):
        self.code = code
        self.name = name
        self.markets = markets
        self.applies_to = applies_to  # product categories
        self.description = description

    def applies(self, product: dict) -> bool:
        cat = (product.get("category") or "general").lower()
        return cat in self.applies_to or "all" in self.applies_to

    def evaluate(self, product: dict) -> RegulationResult:
        raise NotImplementedError


# --------------------------------------------------------------------------
# Helper predicates
# --------------------------------------------------------------------------
def _attr(product: dict, key: str, default=None):
    attrs = product.get("attributes") or {}
    return attrs.get(key, default)


def _b(product: dict, key: str) -> bool:
    return bool(_attr(product, key, False))


def _cat(product: dict) -> str:
    return (product.get("category") or "general").lower()


def _has_any(product: dict, key: str, values: list[str]) -> bool:
    v = _attr(product, key, "")
    if isinstance(v, list):
        return any(str(x).lower() in [str(s).lower() for s in values] for x in v)
    return str(v).lower() in [str(s).lower() for s in values]


# --------------------------------------------------------------------------
# Concrete regulations
# --------------------------------------------------------------------------
class CERegulation(Regulation):
    """EU CE marking umbrella: LVD, EMC, RED, MD, Toy Safety, etc."""

    def __init__(self):
        super().__init__(
            code="CE",
            name="CE Marking (EU)",
            markets=["EU", "EEA"],
            applies_to=["all"],
            description="Products sold in the EU/EEA must carry CE marking where a harmonised "
                        "directive applies, backed by a Declaration of Conformity and technical file.",
        )

    def evaluate(self, product: dict) -> RegulationResult:
        findings: list[Finding] = []
        cat = _cat(product)
        voltage = _attr(product, "voltage", 0)
        wireless = _b(product, "wireless")
        battery = _b(product, "battery")

        # LVD / EMC for anything mains-powered
        if voltage and voltage > 50:
            findings.append(Finding(
                SEV_INFO if voltage > 50 and voltage <= 1000 else SEV_WARNING,
                "Low Voltage Directive (2014/35/EU) applies",
                f"Product operates at {voltage}V AC/DC — requires LVD assessment and DoC.",
                ["LVD test report", "Declaration of Conformity", "Technical file"],
            ))
        if voltage and voltage > 0:
            findings.append(Finding(
                SEV_INFO,
                "EMC Directive (2014/30/EU) applies",
                "Electrical/electronic products require EMC testing (emissions + immunity).",
                ["EMC test report (EN 55032 / EN 55035)", "Declaration of Conformity"],
            ))
        # RED for wireless
        if wireless:
            findings.append(Finding(
                SEV_BLOCKER,
                "Radio Equipment Directive (2014/53/EU) required",
                "Wireless-capable product needs RED assessment, harmonised standards, and DoC.",
                ["RED test report", "RF exposure assessment", "Declaration of Conformity"],
            ))
        # Toy safety
        if cat == "toys":
            findings.append(Finding(
                SEV_BLOCKER,
                "Toy Safety Directive (2009/48/EC) + EN 71",
                "Toys require EN 71 mechanical/physical, flammability, chemical tests and CE marking.",
                ["EN 71-1/2/3 test reports", "DoC", "CE marking"],
            ))
        # Battery directive
        if battery:
            findings.append(Finding(
                SEV_WARNING,
                "Battery Regulation (EU) 2023/1542",
                "Batteries need labelling, capacity marking, and (for portable) removability by 2027.",
                ["Battery label", "Capacity declaration", "Removability assessment"],
            ))

        return self._aggregate("CE", findings)


class FCCRegulation(Regulation):
    """US FCC Part 15 for intentional/unintentional radiators."""

    def __init__(self):
        super().__init__(
            code="FCC",
            name="FCC Part 15 (US)",
            markets=["US"],
            applies_to=["electronics", "wireless", "all"],
            description="Electronic products sold in the US must comply with FCC Part 15 (SDoC or certification for intentional radiators).",
        )

    def evaluate(self, product: dict) -> RegulationResult:
        findings: list[Finding] = []
        cat = _cat(product)
        wireless = _b(product, "wireless")
        has_clock = bool(_attr(product, "voltage", 0)) or cat == "electronics"

        if wireless:
            findings.append(Finding(
                SEV_BLOCKER,
                "FCC Certification required (intentional radiator)",
                "Wireless devices need FCC certification with an FCC ID granted by a TCB.",
                ["FCC ID", "Test report (47 CFR Part 15.247/15.407)", "Grant of Equipment Authorization"],
            ))
        elif has_clock:
            findings.append(Finding(
                SEV_INFO,
                "FCC SDoC may apply (unintentional radiator)",
                "Digital devices >9 kHz need Supplier's Declaration of Conformity under Part 15B.",
                ["SDoC statement", "Test report (Part 15B)"],
            ))
        return self._aggregate("FCC", findings)


class RoHSRegulation(Regulation):
    """EU RoHS 2011/65/EU restricted substances."""

    def __init__(self):
        super().__init__(
            code="RoHS",
            name="RoHS (EU) 2011/65/EU",
            markets=["EU", "EEA", "UK"],
            applies_to=["electronics", "wireless", "all"],
            description="Restricts 10 hazardous substances (lead, mercury, cadmium, etc.) in EEE.",
        )

    def evaluate(self, product: dict) -> RegulationResult:
        findings: list[Finding] = []
        substances = _attr(product, "restricted_substances", []) or []
        substances = [s.lower() for s in substances]
        banned = {"lead", "pb", "mercury", "hg", "cadmium", "cd", "hexavalent chromium",
                  "cr6", "pbb", "pbde", "dehp", "bbp", "dbp", "dibp"}
        hits = sorted(set(substances) & banned)
        if hits:
            findings.append(Finding(
                SEV_BLOCKER,
                "RoHS restricted substance(s) present",
                f"Found: {', '.join(hits)}. Exceeds RoHS 10-substance limits — product cannot be placed on EU market.",
                ["RoHS test report (IEC 62321)", "Supplier declarations", "Homogeneous material analysis"],
            ))
        elif _cat(product) in ("electronics", "wireless"):
            findings.append(Finding(
                SEV_INFO,
                "RoHS compliance declaration needed",
                "Electronic product requires a RoHS compliance declaration + technical documentation.",
                ["RoHS DoC", "Test report or supplier CofC"],
            ))
        return self._aggregate("RoHS", findings)


class REACHRegulation(Regulation):
    """EU REACH SVHC notification."""

    def __init__(self):
        super().__init__(
            code="REACH",
            name="REACH SVHC (EU)",
            markets=["EU", "EEA", "UK"],
            applies_to=["all"],
            description="REACH Regulation (EC) 1907/2006 — SVHCs above 0.1% w/w trigger notification/duty to communicate.",
        )

    def evaluate(self, product: dict) -> RegulationResult:
        findings: list[Finding] = []
        svhc = _attr(product, "svhc", None)
        materials = _attr(product, "materials", []) or []
        if svhc is True or _has_any(product, "restricted_substances", ["lead", "cadmium", "phthalates"]):
            findings.append(Finding(
                SEV_BLOCKER,
                "SVHC above 0.1% w/w — Article 33 duty to inform",
                "Product contains candidate-list SVHC; suppliers and consumers must be informed.",
                ["SVHC declaration", "Article 33 communication", "Supplier analysis"],
            ))
        elif materials:
            risky = {"pvc", "soft plastic", "leather", "textile", "coating", "paint", "ink"}
            if risky & {m.lower() for m in materials}:
                findings.append(Finding(
                    SEV_WARNING,
                    "SVHC screening recommended",
                    f"Materials ({', '.join(materials)}) are common SVHC carriers — obtain supplier declarations.",
                    ["Supplier REACH declarations", "SVHC screening (≤0.1% w/w)"],
                ))
            else:
                findings.append(Finding(
                    SEV_OK,
                    "No obvious SVHC risk",
                    "Materials screened OK; keep supplier declarations on file.",
                ))
        return self._aggregate("REACH", findings)


class GPSRRegulation(Regulation):
    """EU General Product Safety Regulation 2023/988 (applies from Dec 2024)."""

    def __init__(self):
        super().__init__(
            code="GPSR",
            name="GPSR (EU) 2023/988",
            markets=["EU", "EEA", "NI"],
            applies_to=["all"],
            description="All consumer products sold online to the EU need a responsible economic operator, traceability, and visible safety info by 13 Dec 2024.",
        )

    def evaluate(self, product: dict) -> RegulationResult:
        findings: list[Finding] = []
        has_operator = bool(_attr(product, "responsible_operator"))
        has_trace = bool(_attr(product, "traceability"))
        # seller type matters: marketplace sellers are affected; manufacturers too
        findings.append(Finding(
            SEV_BLOCKER if not has_operator else SEV_OK,
            "Responsible economic operator required",
            "GPSR requires a manufacturer/importer/authorised rep (EU or NI) named on the product and listing.",
            ["EU responsible person contact", "Authorised representative agreement"],
        ))
        findings.append(Finding(
            SEV_WARNING if not has_trace else SEV_OK,
            "Traceability info required",
            "Product must carry type/batch number and manufacturer/importer identification.",
            ["Batch/type marking", "Manufacturer + importer identification"],
        ))
        if _cat(product) == "toys":
            findings.append(Finding(
                SEV_WARNING,
                "Online listing safety info",
                "Toy listings must show warnings and safety info directly on the online offer.",
                ["EN 71 warnings on listing", "CE mark visible"],
            ))
        return self._aggregate("GPSR", findings)


class Prop65Regulation(Regulation):
    """California Proposition 65."""

    def __init__(self):
        super().__init__(
            code="Prop65",
            name="California Prop 65",
            markets=["US-CA"],
            applies_to=["all"],
            description="Businesses selling into California must provide clear warnings if products expose consumers to listed chemicals.",
        )

    def evaluate(self, product: dict) -> RegulationResult:
        findings: list[Finding] = []
        substances = [s.lower() for s in (_attr(product, "restricted_substances", []) or [])]
        prop65 = {"lead", "pb", "cadmium", "cd", "phthalates", "bpa", "formaldehyde", "asbestos",
                  "acrylamide", "arsenic", "nickel"}
        hits = sorted(set(substances) & prop65)
        if hits:
            findings.append(Finding(
                SEV_BLOCKER,
                "Prop 65 warning required",
                f"Product may expose California consumers to: {', '.join(hits)}.",
                ["Prop 65 warning label", "Safe harbor exposure assessment"],
            ))
        else:
            findings.append(Finding(
                SEV_OK,
                "No listed chemicals flagged",
                "No Prop 65-listed chemicals detected in attributes; keep formulations reviewed.",
            ))
        return self._aggregate("Prop65", findings)


class CPSIARegulation(Regulation):
    """US CPSIA — children's products."""

    def __init__(self):
        super().__init__(
            code="CPSIA",
            name="CPSIA (US)",
            markets=["US"],
            applies_to=["toys", "children", "all"],
            description="Children's products need CPSC third-party testing, Children's Product Certificate, tracking labels, and lead/phthalate limits.",
        )

    def evaluate(self, product: dict) -> RegulationResult:
        findings: list[Finding] = []
        is_child = _cat(product) in ("toys", "children") or _b(product, "childrens_product")
        if not is_child:
            return self._aggregate("CPSIA", findings, na=True)
        findings.append(Finding(
            SEV_BLOCKER,
            "CPSC third-party testing required",
            "Children's products must be tested by a CPSC-accepted lab per applicable rules.",
            ["CPSC test reports", "Children's Product Certificate (CPC)"],
        ))
        findings.append(Finding(
            SEV_BLOCKER,
            "Tracking label required",
            "Permanent tracking label with manufacturer, date, batch, and source info.",
            ["Tracking label", "Batch records"],
        ))
        findings.append(Finding(
            SEV_WARNING,
            "Lead + phthalate limits",
            "Paint/surface coatings ≤90 ppm lead; substrates ≤100 ppm; phthalates ≤0.1%.",
            ["Lead content test", "Phthalate test"],
        ))
        return self._aggregate("CPSIA", findings)


class UKCARegulation(Regulation):
    """UKCA marking for Great Britain."""

    def __init__(self):
        super().__init__(
            code="UKCA",
            name="UKCA (UK)",
            markets=["UK"],
            applies_to=["electronics", "wireless", "toys", "all"],
            description="UKCA marking applies in Great Britain; products need UK-based responsible person for many categories.",
        )

    def evaluate(self, product: dict) -> RegulationResult:
        findings: list[Finding] = []
        cat = _cat(product)
        voltage = _attr(product, "voltage", 0)
        wireless = _b(product, "wireless")
        if wireless or (voltage and voltage > 50) or cat == "toys":
            findings.append(Finding(
                SEV_WARNING,
                "UKCA conformity assessment",
                "Radio, electrical, and toy products placed on the GB market need UKCA assessment + UK DoC.",
                ["UKCA test reports", "UK Declaration of Conformity", "UK responsible person"],
            ))
        return self._aggregate("UKCA", findings)


class BatteryRegulation(Regulation):
    """EU Battery Regulation 2023/1542."""

    def __init__(self):
        super().__init__(
            code="Battery",
            name="Battery Regulation (EU) 2023/1542",
            markets=["EU", "EEA"],
            applies_to=["electronics", "wireless", "all"],
            description="Portable batteries need labelling, removability/replaceability, and increasingly battery passports.",
        )

    def evaluate(self, product: dict) -> RegulationResult:
        findings: list[Finding] = []
        battery = _b(product, "battery")
        battery_type = _attr(product, "battery_type", "")
        if not battery:
            return self._aggregate("Battery", findings, na=True)
        findings.append(Finding(
            SEV_WARNING,
            "Battery labelling + removability",
            "Portable batteries must be removable/replaceable by end users (enforced from 2027) with proper labelling.",
            ["Removability design review", "Battery label (CE, capacity, chemistry)"],
        ))
        if battery_type in ("li-ion", "lithium-ion", "liion", "li-po", "lipo"):
            findings.append(Finding(
                SEV_WARNING,
                "Li-ion transport + UN38.3",
                "Lithium batteries must pass UN 38.3 and ship under Class 9 dangerous goods rules.",
                ["UN38.3 test summary", "MSDS/SDS", "Dangerous goods declaration"],
            ))
        return self._aggregate("Battery", findings)


class TextileRegulation(Regulation):
    """EU Textile Regulation 1007/2011 + US FTC fiber rules."""

    def __init__(self):
        super().__init__(
            code="Textile",
            name="Textile Labeling (EU/US)",
            markets=["EU", "US"],
            applies_to=["textile", "apparel", "fashion"],
            description="Fiber composition labelling + care labels required on textiles and apparel.",
        )

    def evaluate(self, product: dict) -> RegulationResult:
        findings: list[Finding] = []
        composition = _attr(product, "fiber_composition", "")
        if not composition:
            findings.append(Finding(
                SEV_BLOCKER,
                "Fiber composition label missing",
                "EU Textile Reg. 1007/2011 and US FTC rules require fiber content labels.",
                ["Fiber composition label", "Care label"],
            ))
        else:
            findings.append(Finding(
                SEV_OK,
                "Fiber composition provided",
                f"Composition: {composition}. Ensure label matches in the required language(s).",
            ))
        return self._aggregate("Textile", findings)


class FoodContactRegulation(Regulation):
    """EU 1935/2004 + US FDA food contact."""

    def __init__(self):
        super().__init__(
            code="FoodContact",
            name="Food Contact (EU/US)",
            markets=["EU", "US"],
            applies_to=["food-contact", "kitchen", "cookware"],
            description="Materials intended for food contact need compliance with EU 1935/2004 or US FDA 21 CFR.",
        )

    def evaluate(self, product: dict) -> RegulationResult:
        findings: list[Finding] = []
        materials = [m.lower() for m in (_attr(product, "materials", []) or [])]
        findings.append(Finding(
            SEV_BLOCKER,
            "Food-contact compliance declaration required",
            "Food-contact materials require a Declaration of Compliance + migration testing.",
            ["DoC for food contact", "Migration test report (EU 10/2011 or FDA 21 CFR)"],
        ))
        if any("ceramic" in m or "glass" in m for m in materials):
            findings.append(Finding(
                SEV_WARNING,
                "Ceramic/glass lead-cadmium release",
                "Ceramic ware must meet lead/cadmium release limits (EU 84/500 or FDA).",
                ["Lead/cadmium release test"],
            ))
        return self._aggregate("FoodContact", findings)


class CosmeticRegulation(Regulation):
    """EU Cosmetic Regulation 1223/2009 + US FDA cosmetics."""

    def __init__(self):
        super().__init__(
            code="Cosmetics",
            name="Cosmetics (EU/US)",
            markets=["EU", "US"],
            applies_to=["cosmetics", "beauty", "personal-care"],
            description="Cosmetics need a responsible person, product safety report, and ingredient compliance in the EU; FDA registration/labeling in the US.",
        )

    def evaluate(self, product: dict) -> RegulationResult:
        findings: list[Finding] = []
        findings.append(Finding(
            SEV_WARNING,
            "EU: Responsible Person + CPSR",
            "EU cosmetics require a Responsible Person and a Cosmetic Product Safety Report before sale.",
            ["CPSR", "Responsible person", "Notification via CPNP"],
        ))
        findings.append(Finding(
            SEV_INFO,
            "US: FDA facility + product registration",
            "US MoCRA requires facility registration, product listing, and adverse event reporting.",
            ["FDA facility registration", "Product listing", "Ingredient review"],
        ))
        return self._aggregate("Cosmetics", findings)


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------
REGULATIONS: list[Regulation] = [
    CERegulation(),
    FCCRegulation(),
    RoHSRegulation(),
    REACHRegulation(),
    GPSRRegulation(),
    Prop65Regulation(),
    CPSIARegulation(),
    UKCARegulation(),
    BatteryRegulation(),
    TextileRegulation(),
    FoodContactRegulation(),
    CosmeticRegulation(),
]


def _aggregate_regulation(reg: Regulation, product: dict) -> RegulationResult:
    return reg.evaluate(product)


def evaluate_product(product: dict, markets: list[str] | None = None) -> list[RegulationResult]:
    """Run every applicable regulation for the product's target markets.

    Markets defaults to the product's `market` field (comma-separated).
    Returns results for regulations that apply to at least one target market
    (category applicability is checked by the regulation itself).
    """
    product_markets = {m.strip().upper() for m in (markets or str(product.get("market", "US")).split(","))}
    results: list[RegulationResult] = []
    for reg in REGULATIONS:
        reg_markets = {rm.upper() for rm in reg.markets}
        # Regulation applies if it covers any target market AND the category applies
        if not (product_markets & reg_markets or "ALL" in reg_markets):
            continue
        if not reg.applies(product):
            continue
        try:
            results.append(_aggregate_regulation(reg, product))
        except Exception as exc:  # pragma: no cover
            results.append(RegulationResult(
                code=reg.code, name=reg.name, markets=reg.markets,
                status=STATUS_REVIEW, severity=SEV_WARNING, score=50,
                findings=[Finding(SEV_WARNING, "Evaluation error", str(exc)).to_dict()],
            ))
    return results


def overall_score(results: list[RegulationResult]) -> int:
    if not results:
        return 100
    return max(0, min(100, round(sum(r.score for r in results) / len(results))))


def overall_severity(results: list[RegulationResult]) -> str:
    worst = SEV_OK
    for r in results:
        if SEVERITY_ORDER.get(r.severity, 99) < SEVERITY_ORDER.get(worst, 99):
            worst = r.severity
    return worst


# Patch the base class so subclasses can reuse the aggregation helper.
def _bind_aggregate():
    def _aggregate(self, code: str, findings: list[Finding], na: bool = False):
        if na or not findings:
            status = STATUS_NA if na else STATUS_PASS
            sev = SEV_OK
            score = 100
        else:
            worst = min(findings, key=lambda f: SEVERITY_ORDER.get(f.severity, 99))
            sev = worst.severity
            if sev == SEV_BLOCKER:
                status, score = STATUS_FAIL, 0
            elif sev == SEV_WARNING:
                status, score = STATUS_REVIEW, 55
            else:
                status, score = STATUS_PASS, 90
        return RegulationResult(
            code=code, name=self.name, markets=self.markets,
            status=status, severity=sev, score=score,
            findings=[f.to_dict() for f in findings],
        )

    Regulation._aggregate = _aggregate


_bind_aggregate()
