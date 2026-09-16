const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
function showToast(text){const t=document.createElement('div');t.className='toast';t.textContent=text;document.body.appendChild(t);setTimeout(()=>t.remove(),1800)}
$$('.admin-nav').forEach(btn=>btn.addEventListener('click',()=>{
  $$('.admin-nav').forEach(b=>b.classList.toggle('active',b===btn));
  $$('.admin-view').forEach(v=>v.classList.remove('active'));
  $(`#${btn.dataset.adminView}Admin`).classList.add('active');
}));
const headline=$('#bannerHeadline'),subline=$('#bannerSubline'),cta=$('#bannerCta');
function syncPreview(){
  $('#previewHeadline').innerHTML=headline.value.replace(/ A SMARTER /,'<br>A SMARTER ').replace(/ TOMORROW\./,'<br>TOMORROW.');
  $('#previewSubline').textContent=subline.value; $('#previewCta').textContent=cta.value;
}
[headline,subline,cta].forEach(i=>i.addEventListener('input',syncPreview));
$$('.preview-toggle').forEach(btn=>btn.addEventListener('click',()=>{
  $$('.preview-toggle').forEach(b=>b.classList.toggle('active',b===btn));
  $('#bannerPreview').classList.toggle('mobile',btn.dataset.preview==='mobile');
  $('#bannerPreview').classList.toggle('desktop',btn.dataset.preview==='desktop');
}));
$('#bannerType').addEventListener('change',e=>{
  const map={hero:'Desktop 1920 × 640 px · Mobile 1080 × 720 px',promo:'Desktop 1200 × 320 px · Mobile 1080 × 420 px',background:'Desktop 1920 × 1080 px · Mobile 1080 × 1920 px'};
  $('#resolutionText').textContent=map[e.target.value];
});
$('#saveBanner').addEventListener('click',()=>showToast('Banner uložený v demo režime.'));
$('#resetBanner').addEventListener('click',()=>{headline.value='TENNIS INSIGHTS FOR A SMARTER TOMORROW.';subline.value='ANALYZE • FOLLOW • WIN';cta.value='Zobraziť predikcie';syncPreview()});
$('#sendMessage').addEventListener('click',()=>{if(!$('#messageBody').value.trim())return showToast('Napíš správu.');showToast('Správa odoslaná v demo režime.');$('#messageBody').value='';$('#messageTitle').value=''});
$$('.mini-btn').forEach(b=>b.addEventListener('click',()=>showToast('Účet aktualizovaný v demo režime.')));
