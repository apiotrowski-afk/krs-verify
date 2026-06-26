"""krs-verify — logika weryfikacji podmiotów z KRS i Białej Listy VAT.

Źródła:
  - api-krs.ms.gov.pl  — KRS API MS (odpis aktualny, bez auth)
  - wl-api.mf.gov.pl   — Biała Lista VAT MF (pełne nazwiska reprezentantów,
                          wyszukiwanie po NIP/REGON, limit 100 zapytań/dobę)

Dane zwracane VERBATIM ze źródła — kod nie interpretuje ani nie przetwarza
treści poza formatowaniem do czytelnego tekstu.
"""
from __future__ import annotations

import re
import datetime
import httpx

_HEADERS = {"User-Agent": "krs-verify/0.1 (+https://github.com/apiotrowski-afk/krs-verify)"}
_KRS_BASE = "https://api-krs.ms.gov.pl/api/krs"
_WL_BASE  = "https://wl-api.mf.gov.pl/api"


# ---------------------------------------------------------------------------
# Walidacja numerów
# ---------------------------------------------------------------------------

def validate_krs(krs: str) -> str | None:
    """Zwraca znormalizowany 10-cyfrowy KRS lub None jeśli format błędny."""
    krs = re.sub(r"\s", "", krs)
    if re.fullmatch(r"\d{10}", krs):
        return krs
    if re.fullmatch(r"\d{1,9}", krs):
        return krs.zfill(10)  # uzupełnij zerami z lewej
    return None


def validate_nip(nip: str) -> str | None:
    """Zwraca znormalizowany 10-cyfrowy NIP (z sumą kontrolną) lub None."""
    nip = re.sub(r"[\s\-]", "", nip)
    if not re.fullmatch(r"\d{10}", nip):
        return None
    weights = [6, 5, 7, 2, 3, 4, 5, 6, 7]
    checksum = sum(w * int(d) for w, d in zip(weights, nip)) % 11
    return nip if checksum == int(nip[9]) else None


def validate_regon(regon: str) -> str | None:
    """Zwraca znormalizowany REGON (9 cyfr) lub None."""
    regon = re.sub(r"\s", "", regon)
    if not re.fullmatch(r"\d{9}", regon):
        return None
    weights = [8, 9, 2, 3, 4, 5, 6, 7]
    checksum = sum(w * int(d) for w, d in zip(weights, regon[:8])) % 11
    checksum = 0 if checksum == 10 else checksum
    return regon if checksum == int(regon[8]) else None


# ---------------------------------------------------------------------------
# KRS API
# ---------------------------------------------------------------------------

async def _fetch_krs(krs: str) -> dict | None:
    """Pobiera odpis aktualny z KRS API. Próbuje rejestr=P, potem rejestr=S."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=25, headers=_HEADERS) as c:
        for rejestr in ("P", "S"):
            url = f"{_KRS_BASE}/OdpisAktualny/{krs}?rejestr={rejestr}&format=json"
            resp = await c.get(url)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code not in (404, 400):
                resp.raise_for_status()
    return None


def _is_masked(value: str | None) -> bool:
    return bool(value and "*" in str(value))


def _format_address(siedziba_i_adres: dict) -> str:
    adres  = siedziba_i_adres.get("adres") or {}
    siedz  = siedziba_i_adres.get("siedziba") or {}
    parts  = []
    ulica  = adres.get("ulica") or adres.get("ulicaNazwa") or ""
    nr_d   = adres.get("nrDomu") or ""
    nr_l   = adres.get("nrLokalu") or ""
    kod    = adres.get("kodPocztowy") or adres.get("kodPocztowyCzlon1", "") + \
             ("-" + adres.get("kodPocztowyCzlon2", "") if adres.get("kodPocztowyCzlon2") else "")
    miasto = adres.get("miejscowosc") or adres.get("miejscowoscNazwa") or \
             siedz.get("gmina") or siedz.get("powiat") or ""
    if ulica:
        numer = f"{nr_d}" + (f"/{nr_l}" if nr_l else "")
        parts.append(f"ul. {ulica} {numer}".strip())
    if kod or miasto:
        parts.append(f"{kod} {miasto}".strip())
    if not parts:
        kraj = siedz.get("kraj", "")
        woj  = siedz.get("wojewodztwo", "")
        parts.append(", ".join(filter(None, [kraj, woj])))
    return ", ".join(filter(None, parts)) or "—"


def _format_person(osoba: dict) -> tuple[str, str, bool]:
    """Zwraca (funkcja, imię_nazwisko, czy_zamaskowane)."""
    funkcja  = osoba.get("funkcjaWOrganie") or osoba.get("typWspolnika") or "—"
    naz_obj  = osoba.get("nazwisko") or {}
    im_obj   = osoba.get("imiona") or {}
    nazwisko = naz_obj.get("nazwiskoICzlon") or naz_obj.get("nazwisko") or ""
    imie     = im_obj.get("imie") or ""
    masked   = _is_masked(nazwisko) or _is_masked(imie)
    pelne    = f"{imie} {nazwisko}".strip() if (imie or nazwisko) else "—"
    return funkcja, pelne, masked


def _extract_krs_data(data: dict) -> dict:
    """Wyciąga kluczowe pola z JSON odpisu aktualnego KRS."""
    odpis    = data.get("odpis") or {}
    nagl     = odpis.get("naglowekA") or {}
    dane     = odpis.get("dane") or {}
    dzial1   = dane.get("dzial1") or {}
    dzial2   = dane.get("dzial2") or {}
    dzial3   = dane.get("dzial3") or {}

    podmiot  = dzial1.get("danePodmiotu") or {}
    ident    = podmiot.get("identyfikatory") or {}
    siedz    = dzial1.get("siedzibaIAdres") or {}
    repr_    = dzial2.get("reprezentacja") or {}
    kapital  = dzial2.get("kapital") or dzial2.get("kapitalSpolki") or {}
    likwid   = dzial3.get("informacjeOLikwidacji") or \
               dzial3.get("informacjeOPostepowaniuUpadlosciowym") or {}

    # skład organu
    sklad = repr_.get("sklad") or repr_.get("wspolnicy") or \
            (dzial1.get("wspolnicySpzoo") or [])
    osoby = [_format_person(o) for o in sklad if isinstance(o, dict)]

    # status
    if likwid:
        status = "W LIKWIDACJI / UPADŁOŚCI"
    elif nagl.get("dataWykreslenia"):
        status = "WYKREŚLONA"
    else:
        status = "aktywna"

    # kapitał
    kap_obj  = kapital.get("wysokoscKapitaluZakladowego") or \
               kapital.get("kapitalZakladowy") or {}
    kap_val  = kap_obj.get("wartosc") or kap_obj if isinstance(kap_obj, str) else ""
    kap_wal  = kap_obj.get("waluta") or "PLN"

    return {
        "nazwa":      podmiot.get("nazwa") or "—",
        "forma":      podmiot.get("formaPrawna") or "—",
        "krs":        nagl.get("numerKRS") or "—",
        "nip":        ident.get("nip") or "—",
        "regon":      (ident.get("regon") or "—")[:9],  # KRS zwraca 14-cyfrowy (z kodem jednostki lokalnej); używamy 9-cyfrowego
        "status":     status,
        "stan_na":    nagl.get("stanZDnia") or nagl.get("dataCzasOdpisu", "")[:10],
        "adres":      _format_address(siedz),
        "organ":      repr_.get("nazwaOrganu") or "—",
        "sposob":     repr_.get("sposob") or repr_.get("sposobReprezentacji") or "—",
        "osoby":      osoby,          # list of (funkcja, imie_nazwisko, masked)
        "kapital":    f"{kap_val} {kap_wal}".strip() if kap_val else "—",
        "any_masked": any(m for _, _, m in osoby),
    }


# ---------------------------------------------------------------------------
# WL API (Biała Lista VAT — pełne nazwiska, wyszukiwanie po NIP/REGON)
# ---------------------------------------------------------------------------

async def _fetch_wl(by: str, value: str) -> dict | None:
    """Pobiera dane z Białej Listy VAT. by='nip' lub by='regon'.
    Single-lookup endpoint zwraca result.subject (nie result.entries)."""
    today = datetime.date.today().isoformat()
    url   = f"{_WL_BASE}/search/{by}/{value}?date={today}"
    async with httpx.AsyncClient(follow_redirects=True, timeout=20, headers=_HEADERS) as c:
        resp = await c.get(url)
    if resp.status_code != 200:
        return None
    result = resp.json().get("result") or {}
    return result.get("subject") or None


def _wl_full_names(wl: dict) -> list[tuple[str, str]]:
    """Zwraca listę (rola, imię_nazwisko) z Białej Listy."""
    result = []
    for r in (wl.get("representatives") or []):
        fn = r.get("firstName") or ""
        ln = r.get("lastName") or ""
        result.append(("reprezentant", f"{fn} {ln}".strip()))
    for p in (wl.get("partners") or []):
        fn = p.get("firstName") or ""
        ln = p.get("lastName") or ""
        result.append(("wspólnik", f"{fn} {ln}".strip()))
    return result


def _wl_krs(wl: dict) -> str | None:
    return wl.get("krs") or None


# ---------------------------------------------------------------------------
# Formatowanie odpowiedzi MCP
# ---------------------------------------------------------------------------

_DISCLAIMER = (
    "\n⚠️  Dane pobrane z API KRS/MF mają charakter informacyjny. "
    "Odpis przez API nie zastępuje urzędowego odpisu sądowego tam, gdzie ten jest wymagany.\n"
    "    Zawsze weryfikuj dane z aktualnym odpisem z systemu PRS (prs.ms.gov.pl)."
)


def _render(krs_data: dict, wl_data: dict | None = None) -> str:
    d = krs_data
    lines = [
        f"📋 **{d['nazwa']}**",
        f"KRS {d['krs']}  ·  NIP {d['nip']}  ·  REGON {d['regon']}",
        f"Forma prawna:  {d['forma']}",
        f"Status:        {d['status']}  (stan na: {d['stan_na']})",
        f"",
        f"Siedziba:  {d['adres']}",
        f"",
        f"── Reprezentacja {'─'*46}",
        f"Organ:    {d['organ']}",
        f"Sposób:   {d['sposob']}",
        f"",
    ]

    osoby = d["osoby"]
    if osoby:
        lines.append("Skład:")
        for funkcja, pelne, masked in osoby:
            suffix = "  ⚠️ dane maskowane przez KRS" if masked else ""
            lines.append(f"  {funkcja:<30} {pelne}{suffix}")

    # uzupełnienie z WL gdy KRS maskuje
    if d["any_masked"] and wl_data:
        wl_names = _wl_full_names(wl_data)
        if wl_names:
            lines.append("")
            lines.append("Pełne dane reprezentantów (Biała Lista VAT MF):")
            for rola, imie in wl_names:
                lines.append(f"  {rola:<30} {imie}")

    if d["kapital"] != "—":
        lines += ["", f"── Kapitał {'─'*52}", f"Kapitał zakładowy:  {d['kapital']}"]

    lines.append(_DISCLAIMER)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Publiczne funkcje wywoływane przez server.py
# ---------------------------------------------------------------------------

async def verify_entity(krs_raw: str) -> str:
    krs = validate_krs(krs_raw)
    if not krs:
        return (
            f"❌ Błędny format numeru KRS: '{krs_raw}'\n"
            "KRS to 10 cyfr (z ewentualnymi zerami wiodącymi), np. '0000127088'."
        )

    try:
        raw = await _fetch_krs(krs)
    except httpx.TimeoutException:
        return "❌ Timeout — api-krs.ms.gov.pl nie odpowiada."
    except httpx.HTTPError as e:
        return f"❌ Błąd HTTP: {e}"

    if raw is None:
        return (
            f"❌ Podmiot o numerze KRS {krs} nie został znaleziony.\n"
            "Sprawdź numer KRS lub skorzystaj z wyszukiwarki na prs.ms.gov.pl."
        )

    extracted = _extract_krs_data(raw)

    # opcjonalne uzupełnienie z WL gdy są zamaskowane nazwiska i jest NIP
    wl = None
    if extracted["any_masked"] and extracted["nip"] != "—":
        try:
            wl = await _fetch_wl("nip", extracted["nip"])
        except Exception:
            pass

    return _render(extracted, wl)


async def verify_entity_by_nip(nip_raw: str) -> str:
    nip = validate_nip(nip_raw)
    if not nip:
        return (
            f"❌ Błędny NIP: '{nip_raw}'\n"
            "NIP to 10 cyfr (suma kontrolna nie zgadza się lub zły format)."
        )

    try:
        wl = await _fetch_wl("nip", nip)
    except httpx.TimeoutException:
        return "❌ Timeout — wl-api.mf.gov.pl nie odpowiada."
    except httpx.HTTPError as e:
        return f"❌ Błąd HTTP (Biała Lista): {e}"

    if wl is None:
        return (
            f"❌ Podmiot o NIP {nip} nie znaleziony w Białej Liście VAT.\n"
            "Sprawdź NIP lub użyj verify_entity(krs_number) jeśli znasz numer KRS."
        )

    krs_from_wl = _wl_krs(wl)
    if not krs_from_wl:
        # WL ma dane ale brak KRS (np. JDG spoza KRS) — zwróć co mamy z WL
        name = wl.get("name") or "—"
        addr = wl.get("workingAddress") or wl.get("residenceAddress") or "—"
        reps = _wl_full_names(wl)
        rep_str = "\n".join(f"  {r}: {n}" for r, n in reps) or "  —"
        return (
            f"📋 **{name}**\n"
            f"NIP {nip}  ·  REGON {wl.get('regon', '—')}\n"
            f"(brak numeru KRS — podmiot prawdopodobnie spoza rejestru KRS)\n\n"
            f"Adres: {addr}\n\n"
            f"Reprezentanci (WL MF):\n{rep_str}\n"
            + _DISCLAIMER
        )

    # mamy KRS → pobierz pełne dane z KRS API
    try:
        raw = await _fetch_krs(krs_from_wl)
    except Exception:
        raw = None

    if raw is None:
        return (
            f"⚠️ Znaleziono NIP {nip} → KRS {krs_from_wl}, "
            "ale KRS API nie zwróciło danych. Spróbuj verify_entity('{krs_from_wl}')."
        )

    extracted = _extract_krs_data(raw)
    return _render(extracted, wl)


async def verify_entity_by_regon(regon_raw: str) -> str:
    regon = validate_regon(regon_raw)
    if not regon:
        return (
            f"❌ Błędny REGON: '{regon_raw}'\n"
            "REGON podmiotu prawnego to 9 cyfr (suma kontrolna nie zgadza się lub zły format)."
        )

    try:
        wl = await _fetch_wl("regon", regon)
    except httpx.TimeoutException:
        return "❌ Timeout — wl-api.mf.gov.pl nie odpowiada."
    except httpx.HTTPError as e:
        return f"❌ Błąd HTTP (Biała Lista): {e}"

    if wl is None:
        return (
            f"❌ Podmiot o REGON {regon} nie znaleziony w Białej Liście VAT.\n"
            "Sprawdź REGON lub użyj verify_entity(krs_number) jeśli znasz numer KRS."
        )

    krs_from_wl = _wl_krs(wl)
    if not krs_from_wl:
        return (
            f"❌ Podmiot o REGON {regon} znaleziony w WL, ale nie posiada numeru KRS.\n"
            f"Nazwa: {wl.get('name', '—')}\nAdres: {wl.get('workingAddress', '—')}"
        )

    try:
        raw = await _fetch_krs(krs_from_wl)
    except Exception:
        raw = None

    if raw is None:
        return (
            f"⚠️ Znaleziono REGON {regon} → KRS {krs_from_wl}, "
            "ale KRS API nie zwróciło danych. Spróbuj verify_entity('{krs_from_wl}')."
        )

    extracted = _extract_krs_data(raw)
    return _render(extracted, wl)


def list_supported_registries() -> str:
    return """\
📚 Obsługiwane rejestry

KRS — Krajowy Rejestr Sądowy (api-krs.ms.gov.pl, MS)
  Rejestr P: spółki z o.o., spółki akcyjne, komandytowe, jawne, partnerskie, SKA
  Rejestr S: stowarzyszenia, fundacje, organizacje społeczne i zawodowe, SP ZOZ
  Wyszukiwanie: po numerze KRS (verify_entity)

WL  — Biała Lista Podatników VAT (wl-api.mf.gov.pl, MF)
  Wyszukiwanie: po NIP (verify_entity_by_nip) lub REGON (verify_entity_by_regon)
  Dodatkowe dane: pełne nazwiska reprezentantów, status VAT, rachunki bankowe
  Limit: 100 zapytań/dobę (metoda search)

Nie obsługiwane (brak publicznego API bez klucza):
  CEIDG — jednoosobowe działalności gospodarcze (wymaga klucza API)
  GUS REGON BIR — wymaga formalnego zatwierdzenia dostępu"""
