/* BlinQ private INFO/LIVE screenshot composer and mobile gallery. */
(function(){
  'use strict';
  const MAX_FILES=3, MAX_BYTES=12*1024*1024;
  const TYPES=new Set(['image/png','image/jpeg','image/webp','image/gif','image/avif']);
  const idValid=id=>/^insight-[A-Za-z0-9._-]{6,175}$/.test(String(id||''));
  const escape=s=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const sanitize=value=>Array.isArray(value)?[...new Set(value.filter(idValid))].slice(0,MAX_FILES):[];
  const cache=new Map();
  let scope=null,observer=null;
  function currentScope(){
    try{return String(localStorage.getItem(window.BlinqAuth?.sessionEpochKey?.()||'')||'unavailable');}catch{return 'unavailable';}
  }
  function clearCache(next){
    for(const value of cache.values())Promise.resolve(value).then(url=>{if(url)URL.revokeObjectURL(url);}).catch(()=>{});
    cache.clear();scope=next;
  }
  function loadOne(img){
    if(!img?.isConnected||img.dataset.mediaLoading)return;
    const id=img.dataset.privateInsightImage;if(!idValid(id))return;
    img.dataset.mediaLoading='1';
    const identity=scope;
    if(!cache.has(id))cache.set(id,window.BlinqAuth.insightMedia(id).then(blob=>URL.createObjectURL(blob)));
    cache.get(id).then(url=>{
      if(identity===scope&&img.isConnected)img.src=url;
    }).catch(()=>{
      cache.delete(id);
      if(img.isConnected){img.alt='Obrázok nie je dostupný';img.closest('button')?.classList.add('is-error');}
    });
  }
  function loadImages(root){
    if(!root)return;
    const next=currentScope();if(next!==scope)clearCache(next);
    const images=[...root.querySelectorAll('img[data-private-insight-image]:not([src])')];
    if('IntersectionObserver' in window){
      if(!observer)observer=new IntersectionObserver(entries=>{
        entries.forEach(entry=>{if(entry.isIntersecting){observer.unobserve(entry.target);loadOne(entry.target);}});
      },{rootMargin:'240px'});
      images.forEach(image=>observer.observe(image));
    }else images.forEach(loadOne);
  }
  function gallery(value){
    const ids=sanitize(value);
    if(!ids.length)return '';
    return '<div class="insight-screenshot-gallery">'+ids.map((id,index)=>
      '<button type="button" class="insight-screenshot-open" data-insight-image-open aria-label="Zväčšiť screenshot '+(index+1)+'"><img data-private-insight-image="'+id+'" alt="Screenshot '+(index+1)+'" loading="lazy"></button>'
    ).join('')+'</div>';
  }
  function open(button){
    const source=button?.querySelector('img');if(!source?.src)return;
    const layer=document.createElement('div');layer.className='insight-screenshot-lightbox';
    layer.setAttribute('role','dialog');layer.setAttribute('aria-modal','true');layer.setAttribute('aria-label','Náhľad obrázka');
    const close=document.createElement('button');close.type='button';close.className='insight-screenshot-close';
    close.textContent='×';close.setAttribute('aria-label','Zavrieť obrázok');
    const image=document.createElement('img');image.src=source.src;image.alt=source.alt||'Screenshot';
    layer.append(close,image);
    const dismiss=()=>{layer.remove();document.removeEventListener('keydown',onKey);};
    const onKey=e=>{if(e.key==='Escape')dismiss();};
    close.onclick=dismiss;layer.onclick=e=>{if(e.target===layer)dismiss();};
    document.body.appendChild(layer);document.addEventListener('keydown',onKey);close.focus();
  }
  function idsFor(block){
    try{return sanitize(JSON.parse(block?.dataset?.insightMediaIds||'[]'));}catch{return [];}
  }
  function markup(value){
    return '<div class="admin-insight-upload"><div class="admin-insight-upload-actions">'+
      '<label class="admin-insight-upload-button">＋ Galéria <input data-insight-files type="file" multiple accept="image/png,image/jpeg,image/webp,image/gif,image/avif"></label>'+
      '<label class="admin-insight-upload-button">📷 Odfotiť <input data-insight-camera type="file" accept="image/*" capture="environment"></label>'+
      '<small data-insight-image-count>0/3</small></div>'+
      '<div class="admin-insight-thumbnails" data-insight-previews></div>'+
      '<small class="admin-insight-upload-hint">Screenshot z telefónu, fotka alebo Ctrl+V na počítači. Max. 3 obrázky po 12 MB.</small></div>';
  }
  function preview(block){
    const target=block?.querySelector('[data-insight-previews]');if(!target)return;
    const ids=idsFor(block),pending=block._pendingScreenshots||[];
    target.innerHTML=ids.map((id,index)=>
      '<div class="admin-insight-thumb"><button type="button" data-insight-image-open aria-label="Zväčšiť screenshot"><img data-private-insight-image="'+id+'" alt="Screenshot" loading="lazy"></button><button type="button" data-admin-action="insight-image-remove" data-insight-existing="'+index+'" aria-label="Odstrániť obrázok">×</button></div>'
    ).join('')+pending.map((entry,index)=>
      '<div class="admin-insight-thumb"><button type="button" data-insight-image-open aria-label="Zväčšiť screenshot"><img src="'+escape(entry.url)+'" alt="Nový screenshot"></button><button type="button" data-admin-action="insight-image-remove" data-insight-pending="'+index+'" aria-label="Odstrániť obrázok">×</button></div>'
    ).join('');
    const count=block.querySelector('[data-insight-image-count]');if(count)count.textContent=(ids.length+pending.length)+'/3';
    loadImages(target);
  }
  function notify(value){const status=document.getElementById('adminInsightMessage');if(status)status.textContent=value;}
  function addFiles(block,files){
    const additions=[...files];if(!block||!additions.length)return;
    const pending=block._pendingScreenshots||[];
    if(idsFor(block).length+pending.length+additions.length>MAX_FILES){notify('Najviac 3 obrázky na správu.');return;}
    if(additions.some(file=>!TYPES.has(file.type)||file.size===0||file.size>MAX_BYTES)){
      notify('Použi PNG, JPG, WebP, GIF alebo AVIF do 12 MB na obrázok.');return;
    }
    block._pendingScreenshots=pending.concat(additions.map(file=>({file,url:URL.createObjectURL(file)})));
    notify('Obrázok pridaný. Odošle sa spolu so správou.');
    preview(block);
  }
  function remove(button){
    const block=button.closest('[data-insight-message]');if(!block)return;
    if(button.hasAttribute('data-insight-existing')){
      const ids=idsFor(block);ids.splice(Number(button.dataset.insightExisting),1);
      block.dataset.insightMediaIds=JSON.stringify(ids);
    }else{
      const pending=block._pendingScreenshots||[];
      const removed=pending.splice(Number(button.dataset.insightPending),1)[0];
      if(removed)URL.revokeObjectURL(removed.url);
    }
    preview(block);
  }
  function dispose(block){
    (block?._pendingScreenshots||[]).forEach(entry=>URL.revokeObjectURL(entry.url));
  }
  function wire(form){
    if(!form)return;
    form.querySelectorAll('[data-insight-message]').forEach(preview);
    form.addEventListener('change',e=>{
      if(!e.target.matches('[data-insight-files],[data-insight-camera]'))return;
      addFiles(e.target.closest('[data-insight-message]'),e.target.files||[]);
      e.target.value='';
    });
    form.addEventListener('paste',e=>{
      const block=e.target.closest('[data-insight-message]');if(!block)return;
      const files=[...e.clipboardData?.files||[]].filter(file=>file.type.startsWith('image/'));
      if(files.length){e.preventDefault();addFiles(block,files);}
    });
  }
  async function upload(block,onProgress){
    let ids=idsFor(block);
    const pending=block?._pendingScreenshots||[];
    while(pending.length){
      const item=pending[0];
      if(onProgress)onProgress(ids.length+1);
      const result=await window.BlinqAuth.adminUploadInsightMedia(item.file);
      if(!idValid(result?.media_id))throw new Error('Server nepotvrdil nahratie screenshotu.');
      ids.push(result.media_id);
      block.dataset.insightMediaIds=JSON.stringify(ids);
      URL.revokeObjectURL(item.url);
      pending.shift();
    }
    preview(block);
    return ids;
  }
  window.BlinqInsightMedia={markup,gallery,wire,loadImages,open,remove,dispose,upload,idsFor};
})();