# BlinQ 7.3.6-r23 — visual cleanup audit

This pass removes the retired visual systems that survived earlier UI redesigns while preserving active product controls.

Removed from the shipped runtime: the old header feature strip (including its dead dashboard flags), fixed top/mid/bottom promo banner DOM and renderers, header/content banner configuration inventory, per-membership Hero banner SHOW/BLUR/HIDE/click editor, obsolete banner presets, unused toolbar/sidebar access stubs, no-op navigation drawer compatibility API, unused banner editor help metadata, and CSS selectors proven to belong only to retired visual modules.

The Hero carousel remains the only banner system. It is global across membership levels. Admin → Zobrazenie keeps the intentional per-category and per-row SHOW/BLUR/HIDE controls. The runtime migration sanitizer also deletes retired banner structures from previously published Azure UI configuration so stale storage cannot resurrect the old visual after deploy.

A repository audit and `test_v736_r23_visual_cleanup.py` protect these decisions from regression.
