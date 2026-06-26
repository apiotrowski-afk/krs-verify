"""krs-verify — serwer MCP do weryfikacji podmiotów z KRS.

Transport:
  - Cloud Run (env K_SERVICE lub PORT): streamable-http na 0.0.0.0:$PORT,
    endpoint MCP = /mcp
  - lokalnie (brak PORT): stdio (Claude Desktop / Claude Code)

Publiczny, bez auth — serwuje wyłącznie publiczne dane rejestrowe.
"""
from __future__ import annotations

import logging
import os
import sys

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from krs_verify import core

logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format="[krs-verify] %(message)s")
logger = logging.getLogger(__name__)

mcp = FastMCP("krs-verify")


@mcp.tool()
async def verify_entity(krs_number: str) -> str:
    """Weryfikuje podmiot gospodarczy na podstawie numeru KRS.

    Zwraca AKTUALNE dane z rejestru KRS (api-krs.ms.gov.pl):
    pełna nazwa, forma prawna, KRS/NIP/REGON, adres siedziby,
    organ i sposób reprezentacji, skład zarządu, kapitał zakładowy, status.

    Anti-halucynacja: dane pobierane verbatim z oficjalnego API MS.
    Kluczowe dla oznaczenia strony w umowie i weryfikacji pełnomocnictw.

    Format: 10 cyfr, np. '0000127088' lub '127088' (uzupełni zerami).
    """
    try:
        return await core.verify_entity(krs_number)
    except Exception as e:
        logger.warning("verify_entity blad=%s", type(e).__name__)
        return f"❌ Błąd weryfikacji: {type(e).__name__}: {e}"


@mcp.tool()
async def verify_entity_by_nip(nip: str) -> str:
    """Weryfikuje podmiot na podstawie numeru NIP.

    Przepływ: WL API (Biała Lista VAT MF) → KRS API.
    Zwraca te same dane co verify_entity plus status VAT i rachunki bankowe.
    Pełne nazwiska reprezentantów (nieanonimizowane, ze źródła WL MF).

    Limit WL API: 100 zapytań/dobę. Używaj gdy nie znasz numeru KRS.
    Format NIP: 10 cyfr (z lub bez kresek).
    """
    try:
        return await core.verify_entity_by_nip(nip)
    except Exception as e:
        logger.warning("verify_entity_by_nip blad=%s", type(e).__name__)
        return f"❌ Błąd weryfikacji: {type(e).__name__}: {e}"


@mcp.tool()
async def verify_entity_by_regon(regon: str) -> str:
    """Weryfikuje podmiot na podstawie numeru REGON (9 cyfr).

    Przepływ: WL API (Biała Lista VAT MF) → KRS API.
    Zwraca te same dane co verify_entity.

    Limit WL API: 100 zapytań/dobę.
    """
    try:
        return await core.verify_entity_by_regon(regon)
    except Exception as e:
        logger.warning("verify_entity_by_regon blad=%s", type(e).__name__)
        return f"❌ Błąd weryfikacji: {type(e).__name__}: {e}"


@mcp.tool()
def list_supported_registries() -> str:
    """Lista obsługiwanych rejestrów i ograniczeń (KRS, WL, CEIDG)."""
    return core.list_supported_registries()


def main() -> None:
    port = os.getenv("PORT")
    if os.getenv("K_SERVICE") or port:
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = int(port or "8080")
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False)
        logger.info("krs-verify start: streamable-http na %s:%s (/mcp)",
                    mcp.settings.host, mcp.settings.port)
        mcp.run(transport="streamable-http")
    else:
        logger.info("krs-verify start: stdio (lokalnie)")
        mcp.run()


if __name__ == "__main__":
    main()
