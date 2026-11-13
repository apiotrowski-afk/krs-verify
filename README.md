# krs-verify

**MCP server** do weryfikacji polskich podmiotów gospodarczych z Krajowego Rejestru Sądowego (KRS) i Białej Listy Podatników VAT.

Komplementarny do [legal-cite-pl](https://github.com/apiotrowski-afk/legal-cite-pl) — razem tworzą ekosystem narzędzi anti-halucynacja dla Claude przy pracy z polskimi umowami.

---

## Po co to narzędzie?

Claude może hallucynować dane rejestrowe — błędną nazwę spółki, nieaktualny skład zarządu, zły NIP. Przy oznaczeniu strony w umowie, błędne dane to ryzyko prawne.

`krs-verify` pobiera dane **verbatim z oficjalnych źródeł** (MS, MF) i zwraca je Claude bez żadnego przetwarzania.

## Narzędzia MCP

| Tool | Wejście | Źródło |
|------|---------|--------|
| `verify_entity(krs_number)` | numer KRS (10 cyfr) | api-krs.ms.gov.pl |
| `verify_entity_by_nip(nip)` | NIP (10 cyfr) | wl-api.mf.gov.pl → KRS |
| `verify_entity_by_regon(regon)` | REGON (9 cyfr) | wl-api.mf.gov.pl → KRS |
| `list_supported_registries()` | — | — |

**Zwracane dane:** pełna nazwa, forma prawna, KRS/NIP/REGON, adres siedziby, organ i **sposób reprezentacji**, skład zarządu, kapitał zakładowy, status.

## Źródła danych

- **KRS API** (`api-krs.ms.gov.pl`) — Ministerstwo Sprawiedliwości, odpis aktualny, bez auth
- **WL API** (`wl-api.mf.gov.pl`) — Biała Lista Podatników VAT MF, pełne dane reprezentantów, bez auth (limit: 100 zapytań/dobę)

Nie obsługiwane: CEIDG (wymaga klucza), GUS REGON (wymaga zatwierdzenia).

## Instalacja lokalna (Claude Desktop / Claude Code)

Pakiet instaluje się z tego repozytorium GitHub, nie z PyPI (na PyPI go nie publikujemy).

```json
{
  "mcpServers": {
    "krs-verify": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/apiotrowski-afk/krs-verify", "krs-verify"]
    }
  }
}
```

## Deploy na Google Cloud Run

```bash
gcloud run deploy krs-verify \
  --source . \
  --region europe-west4 \
  --allow-unauthenticated \
  --port 8080
```

Endpoint MCP po deploy: `https://krs-verify-xxxx-lm.a.run.app/mcp`

## ⚠️ Zastrzeżenie

Dane pobierane przez API mają charakter **informacyjny**. Odpis przez API nie zastępuje urzędowego odpisu sądowego tam, gdzie ten jest wymagany przepisami prawa lub postanowieniem umownym. Zawsze weryfikuj dane z aktualnym odpisem z systemu PRS ([prs.ms.gov.pl](https://prs.ms.gov.pl)).

---

## Why this tool?

Polish KRS (National Court Register) data fetched verbatim from the official Ministry of Justice API — no hallucination, no stale training data.

Complementary to [legal-cite-pl](https://github.com/apiotrowski-afk/legal-cite-pl).

**Returns:** full company name, legal form, KRS/NIP/REGON, registered address, representation rules, board composition, share capital, status.

**Sources:** `api-krs.ms.gov.pl` (Ministry of Justice) + `wl-api.mf.gov.pl` (Ministry of Finance VAT list).

**No API keys required.** Public data only.

## License

Apache 2.0
