"""SDK-Pruefung ohne Schluessel und ohne Order (Kriterium E). Auf dem Server nach Installation von deploy/requirements-live.txt:

python -m autotrader.quant.hl_sdk_check [--address 0xDEINEADRESSE]

Prueft: SDK-Version, Wegwerf-Schluessel (nie benutzt, nicht gespeichert), Exchange-Aufbau (liest nur oeffentliche Meta-Daten),
Aufloesung der Spot-Paare UBTC/UETH (Asset-Nummer, Mengen-Dezimalstellen), Bau und lokales Signieren einer Order ohne sie zu senden.
Mit --address: liest das Spot-Konto (oeffentlich) und zeigt, ob unser Parser (hl_exec.fetch_account) das Format versteht.
Es wird nichts gesendet. Es wird kein echter Schluessel gelesen.
"""
import argparse
import importlib.metadata as md

import requests

from . import hl_exec, hl_liquidity, hl_sender


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hl_sdk_check")
    ap.add_argument("--address")
    a = ap.parse_args(argv)
    ver = md.version("hyperliquid-python-sdk")
    print(f"SDK-Version installiert: {ver}, festgenagelt: {hl_sender.SDK_VERSION} -> {'OK' if ver == hl_sender.SDK_VERSION else 'ABWEICHUNG'}")
    import eth_account
    from hyperliquid.exchange import Exchange
    from hyperliquid.utils.signing import get_timestamp_ms, order_request_to_order_wire, order_wires_to_order_action, sign_l1_action
    from hyperliquid.utils.types import Cloid

    s = requests.Session()
    meta, _ = hl_liquidity._post(s, {"type": "spotMetaAndAssetCtxs"})
    acct = eth_account.Account.create()
    ex = Exchange(acct, hl_sender.MAINNET)
    ok = True
    for tok in hl_exec.UNIT.values():
        found = hl_liquidity.find_spot(meta, tok)
        if not found:
            print(f"{tok}: Spot-Paar nicht gefunden")
            ok = False
            continue
        pair = found[1]
        asset = ex.info.name_to_asset(pair)
        szd = ex.info.asset_to_sz_decimals[asset]
        wire = order_request_to_order_wire({"coin": pair, "is_buy": True, "sz": 0.001, "limit_px": 80000.0, "order_type": {"limit": {"tif": "Ioc"}},
                                            "reduce_only": False, "cloid": Cloid.from_str("0x" + "1" * 32)}, asset)
        action = order_wires_to_order_action([wire], None, "na")
        sig = sign_l1_action(acct, action, None, get_timestamp_ms(), None, True)
        print(f"{tok}: Paar {pair}, Asset {asset}, Mengen-Dezimalstellen {szd} (Plan: {hl_exec.fetch_market(s)[1].get(tok)}), lokale Signatur {'OK' if sorted(sig) == ['r', 's', 'v'] else 'unerwartet: ' + str(sorted(sig))}")
        ok = ok and sorted(sig) == ["r", "s", "v"]
    if a.address:
        raw = ex.info.spot_user_state(a.address)
        print("Spot-Konto, Felder:", sorted(raw)[:6], "Salden:", [(b.get("coin"), b.get("total")) for b in raw.get("balances", [])])
        usdc, hold = hl_exec.fetch_account(s, a.address)
        print(f"Unser Parser: USDC {usdc}, Token {hold}")
    print("Ergebnis:", "alles OK, nichts gesendet" if ok else "AUFFAELLIGKEITEN, nicht live gehen")


if __name__ == "__main__":
    main()
