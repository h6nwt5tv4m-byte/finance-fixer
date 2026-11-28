"""Match public business-site rows to filing entities and retain the source monthly detail."""
import re
import unicodedata
from dataclasses import dataclass, field

from pension import require


def public_region(address):
    parts = address.split()
    if not parts:
        return ""
    province = parts[0]
    if province not in {"서울","부산","대구","인천","광주","대전","울산","세종","경기","강원","충북","충남","전북","전남","경북","경남","제주"} and not re.fullmatch(r"[가-힣]+(?:도|시)", province):
        return ""
    if province.startswith("세종") or len(parts) < 2 or not re.fullmatch(r"[가-힣]+[시군구]", parts[1]):
        return province
    count = 3 if parts[1].endswith("시") and len(parts) >= 3 and re.fullmatch(r"[가-힣]+구",parts[2]) else 2
    return " ".join(parts[:count])

# Verified names from DART name-change disclosures, keyed by immutable corporate code.
ALIASES = {"00260213": ("대성", "대성삼경"), "01898642": ("리드넘버", "예서"), "01812554": ("성연", "펍스케일")}


def clean(name):
    value = unicodedata.normalize("NFKC", name).lower()
    return re.sub(r"유한회사|\(유한\)|\(유\)|\s+", "", value)


def stem(name):
    return clean(name).replace("회계법인", "")


@dataclass
class Firm:
    name: str
    code: str = ""
    number: str = ""
    receipt: str = ""
    accounts: dict = field(default_factory=dict)
    monthly: dict = field(default_factory=dict)
    sites: list = field(default_factory=list)
    aliases: tuple = ()
    historical: bool = False

    def record(self):
        values = list(self.monthly.values())
        result = dict(name=self.name, code=self.code, receipt=self.receipt, **self.accounts,
                    months=len(values), personMonths=sum(v[0] for v in values),
                    gained=sum(v[1] for v in values), lost=sum(v[2] for v in values))
        if self.aliases:
            result["aliases"] = list(self.aliases)
        return result


def aggregate(releases, registry, filings, prior_members=(), prior_rows=()):
    current_numbers = set(registry)
    registry = dict(registry)
    known_codes = {}
    names_by_number = {}
    old_names = {r["code"]: list(r.get("aliases", ())) + [r["name"]] for r in prior_rows if "code" in r}
    for name, number, code, *history in prior_members:
        if number:
            registry.setdefault(number, name)
            names_by_number[number] = [name, *(history[0] if history else ())]
        if code:
            known_codes[code] = number
            old_names.setdefault(code, []).append(name)
    members = {stem(name): (number, name) for number, name in registry.items()}
    require(len(members) == len(registry), "한공회 법인명이 겹칩니다")
    entities, aliases = [], {}

    def add_alias(k, firm):
        for prefix in (k + "회계법인", "회계법인" + k):
            require(prefix not in aliases or aliases[prefix] is firm, "다른 법인에 같은 명칭: " + prefix)
            aliases[prefix] = firm

    for code, (reported_name, receipt, accounts) in filings.items():
        names = list(dict.fromkeys((*ALIASES.get(code, ()), stem(reported_name))))
        registered = registry.get(known_codes.get(code))
        if registered:
            names.append(stem(registered))
        names += [stem(n) for n in old_names.get(code, ())]
        names = list(dict.fromkeys(names))
        matched = [k for k in names if k in members]
        require(len(matched) <= 1, "법인 상호 변경과 한공회 명부 확인 필요")
        number, name = members.pop(matched[0]) if matched else ("", reported_name)
        historical = bool(number and number not in current_numbers)
        if historical:
            name = reported_name
        linked_names = [*old_names.get(code, ()), *names_by_number.get(number, ())]
        names.extend(stem(n) for n in linked_names)
        prior_names = tuple(sorted({n for n in linked_names if stem(n) != stem(name)}))
        firm = Firm(name, code, number, receipt, accounts, aliases=prior_names, historical=historical)
        entities.append(firm)
        for k in names:
            add_alias(k, firm)
    for k, (number, name) in members.items():
        old = tuple(sorted({n for n in names_by_number.get(number, ()) if stem(n) != k}))
        firm = Firm(name, number=number, aliases=old, historical=number not in current_numbers)
        for alias in (k, *(stem(n) for n in old)):
            add_alias(alias, firm)
        entities.append(firm)
    prefixes = sorted(aliases, key=len, reverse=True)
    resolved = {}
    for release in releases:
        month = release["month"]
        for row in release["data"]:
            name = clean(row[1])
            if name not in resolved:
                prefix = next((p for p in prefixes if name.startswith(p)), "")
                suffix = name[len(prefix):]
                branch = re.sub(r"\([^()]*\)$", "", suffix)
                separate = re.search(r"근로복지기금|복지재단|세무법인|주식회사|협동조합|노동조합|노조", suffix)
                separate = separate or ("컨설팅" in suffix and not branch.endswith("컨설팅본부"))
                branch_name = re.search(r"(지점|분사무소|분사업소|본부|지사|센터|센타|분실|사무소|팀|점|지부|연구소)$", branch)
                known = branch in {"", "강남", "강서", "부산", "부천", "서초", "종로", "호남"}
                # Some public sites use a person or an English office name in parentheses or after a hyphen.
                resolved[name] = aliases.get(prefix) if not separate and (known or branch_name or suffix.startswith("-")) else None
            firm = resolved[name]
            if firm is None:
                continue
            counts = tuple(map(int, row[7:10]))
            require(min(counts) >= 0, "음수 가입/변동 건수")
            totals = firm.monthly.setdefault(month, [0, 0, 0, 0])
            for i, value in enumerate((*counts, 1)):
                totals[i] += value
            region = public_region(row[4])
            firm.sites.append((month, region, row[2][:6], row[6], *counts, {"1":"등록", "2":"탈퇴"}.get(row[3], row[3])))
    entities.sort(key=lambda f: f.name)
    return entities
