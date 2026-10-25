/** BlinQ reversible optical court preview. Only activated on /court-preview.html. */
(() => {
  'use strict';
  const canvas = document.getElementById('courtCanvas');
  const ctx = canvas.getContext('2d');
  const base = new Image();
  const root = document.getElementById('stage');
  const originalBtn = document.getElementById('btnOriginal');
  const suggestedBtn = document.getElementById('btnSuggested');
  const viewSelect = document.getElementById('viewSelect');
  let showProposed = true;
  const W = 1672, H = 941;
  function line(points, width = 3.3, opacity = .83) {
    ctx.beginPath();
    ctx.moveTo(points[0][0], points[0][1]);
    for (let i=1;i<points.length;i++) ctx.lineTo(points[i][0],points[i][1]);
    ctx.lineWidth = width;
    ctx.strokeStyle = `rgba(221,249,239,${opacity})`;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.stroke();
  }
  function render() {
    ctx.clearRect(0,0,W,H);
    if (!base.complete || !base.naturalWidth) return;
    ctx.drawImage(base,0,0,W,H);
    if (!showProposed) return;
    // Suppress former chaotic marks on the ground; preserve the net mesh unchanged.
    ctx.save();
    const clip = new Path2D();
    clip.moveTo(360,664);
    clip.lineTo(W,660);
    clip.lineTo(W,H);
    clip.lineTo(0,H);
    clip.lineTo(0,842);
    clip.lineTo(360,692);
    clip.closePath();
    ctx.clip(clip);
    ctx.filter = 'blur(24px) brightness(0.76)';
    ctx.drawImage(base,0,0,W,H);
    ctx.restore();
    const g = ctx.createLinearGradient(0,670,0,910);
    g.addColorStop(0,'rgba(4,22,23,.08)');
    g.addColorStop(1,'rgba(2,17,18,.22)');
    ctx.fillStyle = g;
    ctx.fillRect(0,667,W,274);
    // The net remains on the left; court orientation extends left to right.
    line([[364,674],[1232,674]],3.4,.75);
    line([[1232,674],[1554,866]],3.6,.86);
    line([[17,853],[1554,866]],4.0,.88);
    line([[177,749],[1290,722]],3.0,.80);
    line([[726,735],[708,859]],3.1,.80);
    line([[362,677],[19,849]],3.2,.80);
  }
  function syncState() {
    originalBtn.setAttribute('aria-pressed',String(!showProposed));
    suggestedBtn.setAttribute('aria-pressed',String(showProposed));
    render();
  }
  originalBtn.addEventListener('click',()=>{showProposed=false;syncState();});
  suggestedBtn.addEventListener('click',()=>{showProposed=true;syncState();});
  viewSelect.addEventListener('change',()=>{root.dataset.view=viewSelect.value;});
  base.addEventListener('load',render);
  base.src = './assets/blinq_page_background.webp';
})();