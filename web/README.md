# BlinQ — new responsive web

Ľahký statický prototyp BlinQ bez frameworku. Cieľ: rýchle načítanie, rovnaký dátový model pre mobil aj desktop a minimum admin overheadu.

## Verejný web
- TOP → VALUE → ESA → GAMES → SETS → SEE ALL
- ITF nie je samostatná karta; ITF zápasy sa miešajú do normálnych poolov.
- PRIME je skrytý interný pool len pre Comeback LIVE Radar.
- Rookie: 1 pick z každej aktívnej kategórie + Results 24 h.
- PRO: 3 picky z kategórie + Results 48 h.
- ELITE / Legend / GOAT: plný obsah + See All + celá história + LIVE + Premium Info.
- Jedno prediction okno, max 10 riadkov naraz; detail sa otvára do stredu.
- Ľahký SVG loading s dvoma postavičkami a pohybujúcou sa loptou.

## Admin
Iba tri časti:
1. Účty
2. Bannery — Hero / Promo / Background, presné rozmery, HTML text, animácia, Desktop/Mobile preview
3. Správy / LIVE — Premium Info a LIVE signály

Platobné linky, podpisy, FAQ a ostatná konfigurácia majú ísť cez JSON/konfiguračné súbory, nie cez ťažké admin UI.

## Spustenie
Stačí statický server, napr.:

```bash
python3 -m http.server 4173
```

Potom otvoriť `http://localhost:4173/` a admin na `http://localhost:4173/admin.html`.
