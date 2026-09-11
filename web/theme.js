(function(){
  'use strict';
  const KEY='blinq_theme_v1';
  const root=document.documentElement;
  const valid=value=>value==='light'||value==='dark';
  let stored='';
  try{stored=localStorage.getItem(KEY)||'';}catch{}
  const initial=valid(stored)?stored:'light';
  root.dataset.theme=initial;
  root.style.colorScheme=initial;
  function updateMeta(theme){
    const meta=document.querySelector('meta[name="theme-color"]');
    if(meta)meta.setAttribute('content',theme==='dark'?'#08111f':'#eef5ff');
  }
  function apply(theme,persist=true){
    const next=valid(theme)?theme:'light';
    root.dataset.theme=next;
    root.style.colorScheme=next;
    if(document.body)document.body.dataset.theme=next;
    updateMeta(next);
    if(persist){try{localStorage.setItem(KEY,next);}catch{}}
    const button=document.getElementById('themeToggle');
    if(button){
      const dark=next==='dark';
      button.setAttribute('aria-pressed',dark?'true':'false');
      button.setAttribute('aria-label',dark?'Prepnúť na svetlý režim':'Prepnúť na tmavý režim');
      button.title=dark?'Svetlý režim':'Tmavý režim';
    }
    window.dispatchEvent(new CustomEvent('blinq:themechange',{detail:{theme:next}}));
  }
  window.BlinqTheme={get:()=>root.dataset.theme||'light',set:apply,toggle:()=>apply((root.dataset.theme||'light')==='dark'?'light':'dark')};
  document.addEventListener('DOMContentLoaded',()=>{
    apply(root.dataset.theme||initial,false);
    const button=document.getElementById('themeToggle');
    if(button)button.addEventListener('click',()=>window.BlinqTheme.toggle());
  });
})();
