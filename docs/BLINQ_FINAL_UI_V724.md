# BlinQ v7.2.4 — final UI operations

## Footer links

In Admin open the footer/VIP rail editor. There are four entries and each has only three editable values:

1. **Názov** — short card title.
2. **Popis** — one concise supporting sentence.
3. **Odkaz** — internal path such as `/community` or a full `https://...` group/community URL.

If the URL is empty, the card remains visible but is not clickable. External URLs open as external destinations.

Recommended copy length: title up to roughly 24 characters and description up to roughly 55 characters so all four cards remain visually balanced.

## Tournament presentation

The prediction board first attempts the provider tournament logo endpoint through the existing tournament visual resolver. If no provider logo exists, BlinQ uses its local tournament-family fallback. Country flags continue to use the bundled flag assets.

## Table readability

The final board deliberately keeps full match context in the row: tournament, tour/round/surface, both players, pick, market output and confidence. On narrower screens the table scrolls horizontally rather than hiding critical betting/model information.
