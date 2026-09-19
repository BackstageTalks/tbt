# BlinQ 7.3.6-r12 — CI fix

The r11 checks failed before deploy. Four regressions were stale test contracts, not Azure Storage.

- loader scene extracted from base64 SVG into `/assets/blinq_loading_scene_v736.webp`; SVG is a transparent animated rally overlay
- current Hero carousel admin is the banner contract; removed legacy homepage-map assertion
- CSS/JS cache tests read the patch from the `blinq-web-patch` meta instead of hardcoding p=10/p=11
- patch cache bumped to r12 / p=12; release remains 7.3.6 / 7360
