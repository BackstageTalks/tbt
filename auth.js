/* BlinQ 6.8.5 — professionalization pass
   Admin workspace, legal/support content, cookie consent and crisp control details. */

:root{
  --bq-685-panel:#071923;
  --bq-685-panel-2:#0a202c;
  --bq-685-line:rgba(84,142,166,.32);
  --bq-685-line-soft:rgba(126,175,194,.15);
  --bq-685-text:#f3f8fb;
  --bq-685-muted:#91a9b7;
  --bq-685-green:#2df2ad;
  --bq-685-violet:#8b5cf6;
  --bq-685-danger:#ff617d;
  --bq-685-warning:#f7c865;
}

/* Crisp SVG controls ------------------------------------------------------ */
.dialog-close,
.insight-drawer-head button,
.profile-toggle,
.daily-expand,
.icon-text-btn{
  -webkit-font-smoothing:antialiased;
  text-rendering:geometricPrecision;
}
.dialog-close svg,
.insight-drawer-head button svg,
.profile-toggle svg,
.daily-expand svg,
.icon-text-btn svg,
.admin-search-icon svg,
.admin-side-foot a svg,
.admin-more-actions svg{
  width:18px;height:18px;display:block;fill:none;stroke:currentColor;stroke-width:1.7;
  stroke-linecap:round;stroke-linejoin:round;vector-effect:non-scaling-stroke;
}
.dialog-close{
  width:38px!important;height:38px!important;min-width:38px;border-radius:12px!important;
  display:grid!important;place-items:center;padding:0!important;border:1px solid rgba(101,164,188,.34)!important;
  color:#a8c4d0!important;background:rgba(7,26,37,.92)!important;box-shadow:none!important;
  transition:border-color .16s ease,color .16s ease,background .16s ease,transform .16s ease;
}
.dialog-close:hover{color:#fff!important;border-color:rgba(45,242,173,.55)!important;background:#0a2632!important;transform:translateY(-1px)}
.dialog-close:focus-visible{outline:2px solid var(--bq-685-green);outline-offset:2px}
.icon-text-btn{display:inline-flex!important;align-items:center;gap:7px}.icon-text-btn svg{width:15px;height:15px}

/* Admin becomes an internal workspace instead of another public page ------- */
body.blinq-admin #vipRail,
body.blinq-admin .site-footer,
body.blinq-admin #mobileTabs{display:none!important}
body.blinq-admin .route-heading{display:none!important}
body.blinq-admin .route-panel{padding-top:12px!important}
body.blinq-admin .dashboard-topbar .reference-navigation,
body.blinq-admin .dashboard-topbar .reference-search{opacity:.42}

.admin-console-v685{
  width:min(1560px,calc(100vw - 30px));margin:0 auto 28px;
  display:grid;grid-template-columns:226px minmax(0,1fr);gap:18px;align-items:start;
}
.admin-side-nav{
  position:sticky;top:82px;min-height:calc(100vh - 104px);padding:16px 12px;
  border:1px solid var(--bq-685-line);border-radius:18px;
  background:linear-gradient(180deg,rgba(8,29,40,.98),rgba(5,20,29,.98));
  box-shadow:0 20px 50px rgba(0,0,0,.18);display:flex;flex-direction:column;gap:14px;
}
.admin-side-brand{padding:4px 8px 12px;border-bottom:1px solid var(--bq-685-line-soft);display:grid;gap:3px}
.admin-side-brand>span,.admin-workarea-head>div>small{font-size:9px;letter-spacing:.16em;font-weight:800;color:#a778ff}
.admin-side-brand strong{font-size:18px;line-height:1.2;color:#fff;letter-spacing:-.025em}
.admin-side-brand small{font-size:11px;color:var(--bq-685-muted)}
.admin-tabs-v685{display:grid!important;grid-template-columns:1fr!important;gap:5px!important;margin:0!important;padding:0!important;border:0!important;background:none!important}
.admin-tabs-v685 button{
  min-height:50px;width:100%;padding:8px 9px!important;border:1px solid transparent!important;border-radius:11px!important;
  background:transparent!important;color:#91a9b7!important;text-align:left!important;display:grid!important;
  grid-template-columns:3px minmax(0,1fr)!important;gap:10px!important;align-items:center!important;box-shadow:none!important;
}
.admin-tabs-v685 button:hover{background:rgba(37,88,105,.16)!important;color:#dcebf1!important}
.admin-tabs-v685 button.active{background:linear-gradient(90deg,rgba(125,77,246,.18),rgba(31,74,88,.18))!important;border-color:rgba(137,91,246,.36)!important;color:#fff!important}
.admin-nav-mark{height:26px;width:3px;border-radius:99px;background:transparent}
.admin-tabs-v685 button.active .admin-nav-mark{background:var(--bq-685-violet);box-shadow:0 0 14px rgba(139,92,246,.55)}
.admin-tabs-v685 button>span:last-child{display:grid;gap:2px;min-width:0}.admin-tabs-v685 strong{font-size:12px!important;line-height:1.1}.admin-tabs-v685 small{font-size:9px!important;color:#668494!important;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.admin-tabs-v685 button.active small{color:#9bb1bd!important}
.admin-side-foot{margin-top:auto;border-top:1px solid var(--bq-685-line-soft);padding-top:12px;display:grid;gap:7px}
.admin-side-foot .admin-diagnostics-button,.admin-side-foot a{width:100%;justify-content:flex-start!important;min-height:38px;border-radius:10px!important;font-size:10px!important;padding:0 10px!important;text-decoration:none;display:flex;align-items:center;gap:8px}
.admin-side-foot a{color:#8faab6;border:1px solid transparent}.admin-side-foot a:hover{color:#e7f4f8;background:rgba(255,255,255,.03)}
.admin-health-dot{width:7px;height:7px;border-radius:50%;background:#7c91a0;box-shadow:0 0 0 3px rgba(124,145,160,.08)}
.admin-diagnostics-button.is-ok .admin-health-dot{background:var(--bq-685-green);box-shadow:0 0 12px rgba(45,242,173,.6)}
.admin-diagnostics-button.is-warning .admin-health-dot{background:var(--bq-685-warning);box-shadow:0 0 12px rgba(247,200,101,.4)}

.admin-workarea{min-width:0;display:grid;gap:13px}
.admin-workarea-head{
  min-height:85px;padding:17px 19px;border:1px solid var(--bq-685-line);border-radius:18px;
  background:linear-gradient(120deg,rgba(7,28,39,.98),rgba(6,23,32,.96));display:flex;align-items:center;justify-content:space-between;gap:18px;
}
.admin-workarea-head h2{margin:4px 0 3px;color:#fff;font-size:23px;line-height:1;letter-spacing:-.035em}.admin-workarea-head p{margin:0;color:#8da6b3;font-size:11px}
.admin-workarea-head .admin-global-actions{display:flex;align-items:center;justify-content:flex-end;gap:7px;flex-wrap:wrap}
.admin-account-direct-note{display:inline-flex;align-items:center;gap:7px;padding:8px 10px;border:1px solid rgba(45,242,173,.19);border-radius:10px;background:rgba(45,242,173,.055);color:#9eb8b0;font-size:9px}
.admin-account-direct-note>span{width:6px;height:6px;border-radius:50%;background:var(--bq-685-green);box-shadow:0 0 10px rgba(45,242,173,.5)}
.admin-more-actions{position:relative}.admin-more-actions>summary{list-style:none;width:37px;height:37px;border:1px solid var(--bq-685-line);border-radius:10px;display:grid;place-items:center;cursor:pointer;color:#9db6c1}.admin-more-actions>summary::-webkit-details-marker{display:none}.admin-more-actions>div{position:absolute;right:0;top:43px;z-index:30;min-width:160px;padding:7px;border:1px solid var(--bq-685-line);border-radius:11px;background:#081b25;box-shadow:0 16px 34px rgba(0,0,0,.3);display:grid;gap:4px}.admin-more-actions button{border:0;background:none;color:#bad0d9;padding:8px;border-radius:8px;text-align:left;cursor:pointer}.admin-more-actions button:hover{background:rgba(255,255,255,.05);color:#fff}
.admin-panel-v685{border:1px solid var(--bq-685-line);border-radius:18px;background:rgba(5,22,31,.82);padding:16px;min-width:0;overflow:hidden}
.admin-panel-v685 .admin-ux-section{margin:0!important}

/* Accounts and manual payments ------------------------------------------- */
.admin-search-icon{display:grid;place-items:center;width:18px;color:#67899a}.admin-search-icon svg{width:15px;height:15px}
.admin-payment-ledger{border-color:rgba(139,92,246,.25)!important;background:linear-gradient(135deg,rgba(139,92,246,.045),rgba(8,31,42,.08))!important}
.admin-payment-form{display:grid;gap:10px}.admin-payment-actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.admin-payment-actions>span{font-size:10px;color:#9db5c0}
.admin-payment-history{display:grid;gap:7px;margin-top:9px}.admin-user-payment{display:grid;grid-template-columns:100px 115px minmax(140px,1fr) minmax(180px,1.4fr);gap:10px;align-items:center;padding:10px 11px;border:1px solid var(--bq-685-line-soft);border-radius:10px;background:rgba(4,18,26,.5)}
.admin-user-payment strong{font-size:12px;color:#fff}.admin-user-payment small,.admin-user-payment span{font-size:9px;color:#8fa8b4}.admin-payment-empty{padding:14px;border:1px dashed var(--bq-685-line);border-radius:10px;color:#8099a6;font-size:10px;text-align:center}

/* Support ---------------------------------------------------------------- */
.admin-support-filters{display:flex;gap:7px;flex-wrap:wrap;margin:14px 0}.admin-support-filters button{border:1px solid var(--bq-685-line);background:#071b25;color:#8fa9b5;border-radius:99px;padding:7px 10px;font-size:9px;cursor:pointer}.admin-support-filters button b{margin-left:6px;color:#dceaf0}.admin-support-filters button.active{border-color:rgba(139,92,246,.55);background:rgba(139,92,246,.13);color:#fff}
.admin-support-list{display:grid;gap:9px}.admin-support-ticket{padding:14px;border:1px solid var(--bq-685-line-soft);border-radius:13px;background:rgba(4,18,26,.48)}.admin-support-ticket>header{display:flex;justify-content:space-between;gap:12px}.admin-support-ticket header div{display:grid;gap:2px}.admin-support-ticket header small{font-size:8px;color:#667f8e;letter-spacing:.1em}.admin-support-ticket header strong{font-size:13px;color:#fff}.admin-support-meta{display:flex;gap:12px;flex-wrap:wrap;margin:8px 0;color:#7f9aa7;font-size:9px}.admin-support-ticket>p{margin:10px 0 13px;color:#c1d2d9;font-size:11px;line-height:1.55;white-space:pre-wrap}.support-status{font-size:8px;font-weight:800;letter-spacing:.08em;border-radius:99px;padding:6px 8px;height:max-content}.support-status.is-new{color:#b799ff;background:rgba(139,92,246,.12)}.support-status.is-in_progress{color:#f1cd73;background:rgba(247,200,101,.09)}.support-status.is-resolved{color:#4df3b7;background:rgba(45,242,173,.08)}
.admin-support-controls{display:grid;grid-template-columns:145px minmax(200px,1fr) auto;gap:8px;align-items:end}.admin-support-controls label{display:grid;gap:5px;color:#7894a1;font-size:8px}.admin-support-controls input,.admin-support-controls select{min-height:36px;border-radius:9px!important}

/* System health ----------------------------------------------------------- */
.admin-system-cards{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px;margin:14px 0}.admin-system-card{position:relative;padding:12px 10px;border:1px solid var(--bq-685-line-soft);border-radius:12px;background:rgba(5,22,30,.65);display:grid;gap:4px;min-width:0}.admin-system-card>span{position:absolute;right:9px;top:9px;width:7px;height:7px;border-radius:50%;background:#738995}.admin-system-card.is-ok>span{background:var(--bq-685-green);box-shadow:0 0 11px rgba(45,242,173,.5)}.admin-system-card.is-warning>span{background:var(--bq-685-warning)}.admin-system-card.is-error>span{background:var(--bq-685-danger)}.admin-system-card small{font-size:7px;letter-spacing:.1em;color:#6e8997;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.admin-system-card strong{font-size:13px;color:#fff}.admin-system-card em{font-size:8px;color:#78939f;font-style:normal;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.admin-system-details{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-bottom:14px}.admin-system-details>div{padding:10px;border:1px solid var(--bq-685-line-soft);border-radius:10px;display:grid;gap:3px}.admin-system-details small{font-size:8px;color:#6f8b99}.admin-system-details strong{font-size:10px;color:#d9e9ef}.ops-level{display:inline-flex;padding:4px 6px;border-radius:99px;font-size:7px;font-weight:800}.ops-level.is-error{color:#ff8aa0;background:rgba(255,97,125,.1)}.ops-level.is-warning{color:#f7cf77;background:rgba(247,200,101,.1)}.ops-level.is-info{color:#91b6c6;background:rgba(86,150,176,.1)}

/* Content / legal admin cards -------------------------------------------- */
.admin-content-pages{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:14px 0}.admin-content-pages article{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:11px 12px;border:1px solid var(--bq-685-line-soft);border-radius:11px;background:rgba(5,22,30,.45)}.admin-content-pages article>div{display:grid;gap:2px}.admin-content-pages small{font-size:7px;text-transform:uppercase;letter-spacing:.12em;color:#627f8e}.admin-content-pages strong{font-size:11px;color:#edf6f9}.admin-content-pages span{font-size:8px;color:#7d98a4}

/* Public content pages ---------------------------------------------------- */
.content-page{width:min(1040px,100%);margin:0 auto 32px;display:grid;gap:16px}.content-page-hero{padding:24px 26px;border:1px solid rgba(79,139,161,.28);border-radius:18px;background:radial-gradient(circle at 80% 0,rgba(45,242,173,.06),transparent 34%),linear-gradient(135deg,rgba(7,28,39,.98),rgba(5,21,30,.98))}.content-page-hero>span{display:block;color:#a778ff;font-size:9px;letter-spacing:.17em;font-weight:800}.content-page-hero h2{margin:7px 0 7px;color:#fff;font-size:clamp(27px,4vw,42px);line-height:1;letter-spacing:-.045em}.content-page-hero>p{max-width:760px;margin:0;color:#9bb0ba;font-size:12px;line-height:1.6}.content-meta{display:flex;gap:12px;flex-wrap:wrap;margin-top:15px;padding-top:12px;border-top:1px solid rgba(113,162,180,.14);font-size:9px;color:#728f9d}.content-meta strong{color:#bdd2db}.content-section-grid{display:grid;gap:9px}.content-section-card{padding:18px 19px;border:1px solid rgba(76,131,153,.21);border-radius:14px;background:rgba(6,23,32,.68);display:grid;grid-template-columns:34px 1fr;gap:13px}.content-section-index{font-size:9px;color:#6f8d9a;letter-spacing:.1em;padding-top:4px}.content-section-card h3{margin:0 0 7px;color:#edf6f9;font-size:14px}.content-section-card p{margin:0;color:#9db1ba;line-height:1.72;font-size:11px;white-space:pre-line}.content-faq-list{display:grid;gap:7px}.content-faq{border:1px solid rgba(76,131,153,.22);border-radius:12px;background:rgba(6,23,32,.7);overflow:hidden}.content-faq summary{list-style:none;cursor:pointer;padding:14px 16px;display:flex;align-items:center;justify-content:space-between;gap:12px;color:#e7f2f6;font-size:11px;font-weight:700}.content-faq summary::-webkit-details-marker{display:none}.content-faq summary svg{width:16px;height:16px;fill:none;stroke:#7798a6;stroke-width:1.7}.content-faq[open] summary svg{transform:rotate(180deg)}.content-faq p{margin:0;padding:0 16px 15px;color:#91a9b4;font-size:10px;line-height:1.65}

/* Support page ------------------------------------------------------------ */
.support-panel{padding:19px;border:1px solid rgba(139,92,246,.25);border-radius:16px;background:linear-gradient(135deg,rgba(139,92,246,.055),rgba(5,22,31,.84));display:grid;grid-template-columns:minmax(180px,.65fr) minmax(0,1.35fr);gap:20px}.support-panel-copy>span{font-size:8px;letter-spacing:.15em;font-weight:800;color:#a980ff}.support-panel-copy h3{margin:7px 0;color:#fff;font-size:19px}.support-panel-copy p{margin:0;color:#8ea6b1;font-size:10px;line-height:1.65}.support-form{display:grid;gap:10px}.support-form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.support-form-grid label{display:grid;gap:5px;color:#7e99a5;font-size:8px}.support-form-grid .span-2{grid-column:1/-1}.support-form input,.support-form select,.support-form textarea{width:100%;border:1px solid rgba(80,139,161,.32);border-radius:10px;background:#061924;color:#edf7fa;padding:10px 11px;font:inherit;outline:none}.support-form input:focus,.support-form select:focus,.support-form textarea:focus{border-color:rgba(45,242,173,.55);box-shadow:0 0 0 2px rgba(45,242,173,.06)}.support-form-actions{display:flex;align-items:center;gap:10px}.support-form-actions span{font-size:9px;color:#8ba7b2}.support-form>small{font-size:8px;color:#677f8b}

/* Logged-out public document modal --------------------------------------- */
.public-content-dialog{width:min(920px,calc(100vw - 28px));max-height:min(88vh,920px);padding:0;border:1px solid rgba(81,144,167,.36);border-radius:20px;background:#04141d;color:#fff;box-shadow:0 32px 90px rgba(0,0,0,.62);overflow:auto}.public-content-dialog::backdrop{background:rgba(0,7,11,.78);backdrop-filter:blur(8px)}.public-content-dialog>.dialog-close{position:sticky!important;top:14px!important;float:right;z-index:5;margin:14px 14px -52px 0}.public-content-dialog #publicContentDialogContent{padding:70px 22px 22px}.public-content-dialog .content-page{margin-bottom:0}.public-content-dialog .content-page-hero h2{font-size:30px}
.cookie-settings-card{margin:0 auto 20px;width:min(1040px,100%);padding:16px;border:1px solid rgba(45,242,173,.19);border-radius:13px;background:rgba(45,242,173,.035)}.cookie-settings-card strong{display:block;color:#eaf7f3;font-size:12px}.cookie-settings-card p{color:#86a39f;font-size:9px}.cookie-settings-card>div{display:flex;gap:8px;flex-wrap:wrap}

/* Signup legal consent ---------------------------------------------------- */
.auth-consent{display:flex!important;align-items:flex-start!important;gap:8px!important;margin-top:2px;padding:9px 10px;border:1px solid rgba(95,148,166,.18);border-radius:10px;background:rgba(5,26,35,.5);color:#89a2ad!important;font-size:9px!important;line-height:1.45!important}.auth-consent[hidden]{display:none!important}.auth-consent input{width:15px!important;height:15px!important;min-width:15px;margin:1px 0 0;accent-color:var(--bq-685-green)}.auth-consent button{border:0;padding:0;background:none;color:#b69aff;font:inherit;text-decoration:underline;text-decoration-color:rgba(182,154,255,.45);cursor:pointer}.auth-consent button:hover{color:#d4c1ff}

/* Cookie consent ---------------------------------------------------------- */
.cookie-consent{position:fixed;z-index:10000;left:50%;bottom:max(18px,env(safe-area-inset-bottom));transform:translateX(-50%);width:min(850px,calc(100vw - 28px));padding:14px 15px;border:1px solid rgba(87,149,171,.38);border-radius:15px;background:rgba(4,20,28,.97);box-shadow:0 20px 60px rgba(0,0,0,.45);backdrop-filter:blur(14px);display:grid;grid-template-columns:1fr auto;gap:16px;align-items:center}.cookie-consent[hidden]{display:none!important}.cookie-consent-copy{display:grid;gap:3px}.cookie-consent-copy>span{font-size:7px;letter-spacing:.14em;color:#a77eff;font-weight:800}.cookie-consent-copy>strong{font-size:12px;color:#f0f8fa}.cookie-consent-copy>p{margin:0;color:#8ca5b0;font-size:9px;line-height:1.45}.cookie-consent-copy>button{width:max-content;padding:0;border:0;background:none;color:#9ec0cb;font-size:8px;text-decoration:underline;cursor:pointer}.cookie-consent-actions{display:flex;gap:7px;align-items:center;white-space:nowrap}

/* Footer can now carry legal/support links without collapsing ------------- */
.site-footer .footer-left{min-width:0}.site-footer #footerLearnNavigation{display:flex;align-items:center;gap:13px;flex-wrap:wrap}.site-footer #footerLearnNavigation a{white-space:nowrap}
.system-status.is-warning i{background:var(--bq-685-warning)!important;box-shadow:0 0 10px rgba(247,200,101,.5)!important}.system-status.is-error i{background:var(--bq-685-danger)!important;box-shadow:0 0 10px rgba(255,97,125,.5)!important}

/* General detail polish --------------------------------------------------- */
.admin-panel-v685 button,.admin-panel-v685 input,.admin-panel-v685 select,.admin-panel-v685 textarea{font-family:inherit}
.admin-panel-v685 .btn{border-radius:10px;min-height:36px}
.admin-panel-v685 input,.admin-panel-v685 select,.admin-panel-v685 textarea{border-radius:9px!important}
.admin-analytics-head>.btn[data-admin-action="refresh-analytics"]{font-size:0}.admin-analytics-head>.btn[data-admin-action="refresh-analytics"]::before{content:'Obnoviť';font-size:10px}

@media(max-width:1180px){
  .admin-console-v685{grid-template-columns:195px minmax(0,1fr)}
  .admin-system-cards{grid-template-columns:repeat(3,minmax(0,1fr))}
  .admin-user-payment{grid-template-columns:90px 100px minmax(120px,1fr)}.admin-user-payment>span:last-child{grid-column:1/-1}
}
@media(max-width:900px){
  body.blinq-admin .dashboard-topbar .reference-navigation,body.blinq-admin .dashboard-topbar .reference-search{display:none!important}
  .admin-console-v685{width:min(100% - 20px,900px);grid-template-columns:1fr}
  .admin-side-nav{position:static;min-height:0;padding:10px}.admin-side-brand{display:none}.admin-tabs-v685{grid-template-columns:repeat(4,minmax(0,1fr))!important;overflow:auto}.admin-tabs-v685 button{min-width:120px}.admin-side-foot{display:none}
  .admin-workarea-head{min-height:0}.admin-workarea-head{align-items:flex-start;flex-direction:column}.admin-workarea-head .admin-global-actions{justify-content:flex-start}
  .admin-support-controls{grid-template-columns:1fr 1fr}.admin-support-controls .btn{grid-column:1/-1}.admin-content-pages{grid-template-columns:1fr}.support-panel{grid-template-columns:1fr}.admin-system-details{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media(max-width:620px){
  .admin-console-v685{width:calc(100% - 12px);gap:9px}.admin-side-nav{border-radius:13px}.admin-tabs-v685{grid-template-columns:repeat(3,124px)!important}.admin-tabs-v685 button{min-height:44px}.admin-tabs-v685 small{display:none}
  .admin-panel-v685{padding:9px;border-radius:13px}.admin-workarea-head{padding:13px;border-radius:13px}.admin-workarea-head h2{font-size:19px}
  .admin-system-cards{grid-template-columns:repeat(2,minmax(0,1fr))}.admin-system-details{grid-template-columns:1fr}.admin-support-controls{grid-template-columns:1fr}.admin-user-payment{grid-template-columns:1fr 1fr}.admin-user-payment>span:last-child{grid-column:1/-1}
  .content-page-hero{padding:19px 17px;border-radius:14px}.content-page-hero h2{font-size:27px}.content-section-card{padding:15px 13px;grid-template-columns:26px 1fr}.support-form-grid{grid-template-columns:1fr}.support-form-grid .span-2{grid-column:auto}
  .public-content-dialog{width:calc(100vw - 12px);max-height:94vh;border-radius:15px}.public-content-dialog #publicContentDialogContent{padding:62px 10px 12px}
  .cookie-consent{width:calc(100vw - 16px);bottom:8px;grid-template-columns:1fr;gap:10px}.cookie-consent-actions{justify-content:stretch}.cookie-consent-actions .btn{flex:1}
}
.admin-account-history{background:rgba(4,18,26,.38)!important}.admin-account-history-row{display:grid;grid-template-columns:105px minmax(0,1fr) minmax(100px,.35fr);gap:10px;align-items:center;padding:9px 10px;border-top:1px solid var(--bq-685-line-soft)}.admin-account-history-row:first-of-type{border-top:0}.admin-account-history-row>span{font-size:9px;color:#9bb0ba;display:flex;gap:5px}.admin-account-history-row>span small{color:#627e8c}.admin-account-history-row strong{font-size:9px;color:#d8e7ed;font-weight:600;line-height:1.4}.admin-account-history-row em{font-size:8px;color:#758f9c;font-style:normal;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
@media(max-width:620px){.admin-account-history-row{grid-template-columns:1fr}.admin-account-history-row>span{order:2}.admin-account-history-row em{order:3}}
.vip-feature-svg{display:grid;place-items:center}.vip-feature-svg svg{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}.inline-lock-icon{width:15px;height:15px;margin-right:6px;vertical-align:-2px;fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}.profile-logout-icon{display:grid;place-items:center}.profile-logout-icon svg{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:1.65;stroke-linecap:round;stroke-linejoin:round}
@media(min-width:901px){body.blinq-admin .dashboard-topbar .reference-navigation,body.blinq-admin .dashboard-topbar .reference-search{display:none!important}body.blinq-admin .dashboard-topbar{grid-template-columns:auto 1fr auto!important}body.blinq-admin .dashboard-topbar .topbar-actions{grid-column:3}}
.admin-panel-v685 .admin-form-section-title{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}.admin-panel-v685 .admin-form-section-title>span{display:block;margin:0!important;color:#78939f;font-size:9px;line-height:1.45}.admin-panel-v685 .admin-form-section-title>strong{font-size:10px;color:#dce9ee}.admin-panel-v685 .admin-form-section-title.compact{margin-top:14px;padding-top:11px;border-top:1px solid var(--bq-685-line-soft)}
.admin-system-cards{grid-template-columns:repeat(5,minmax(0,1fr))}
@media(max-width:1180px){.admin-system-cards{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:620px){.admin-system-cards{grid-template-columns:repeat(2,minmax(0,1fr))}}

/* Brand consistency: green actions instead of legacy violet ------------- */
.cookie-consent-copy>span{color:#2df2ad!important}
.cookie-consent .btn-primary,.cookie-settings-card .btn-primary{border-color:#2df2ad!important;background:linear-gradient(135deg,#2df2ad,#43e5bd)!important;color:#041510!important;box-shadow:0 8px 24px rgba(45,242,173,.15)!important}
