(() => {
  'use strict';
  const API_KEY='AIzaSyDMH_CDVsJL_nu369r-s3kQDYpGrSfzevE';
  const $=id=>document.getElementById(id);
  const params=new URLSearchParams(location.search);
  const mode=params.get('mode')||'';
  const code=params.get('oobCode')||'';
  const endpoint=action=>`https://identitytoolkit.googleapis.com/v1/accounts:${action}?key=${encodeURIComponent(API_KEY)}`;
  async function call(action,body){
    const r=await fetch(endpoint(action),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const d=await r.json().catch(()=>({}));
    if(!r.ok){const e=new Error(String(d?.error?.message||d?.error||'Action failed'));e.code=String(d?.error?.message||'');throw e;}return d;
  }
  function show(title,sk,en,{error=false,home=true}={}){$('title').textContent=title;$('copy').textContent=sk;$('copyEn').textContent=en;$('status').classList.toggle('error',error);if(home)$('home').classList.remove('hidden');}
  function errorText(code){
    if(/EXPIRED_OOB_CODE/i.test(code))return ['Odkaz už vypršal. Vyžiadajte si nový e-mail.','This link has expired. Request a new email.'];
    if(/INVALID_OOB_CODE/i.test(code))return ['Odkaz je neplatný alebo už bol použitý.','This link is invalid or has already been used.'];
    if(/WEAK_PASSWORD/i.test(code))return ['Zvoľte silnejšie heslo s minimálne 8 znakmi.','Choose a stronger password with at least 8 characters.'];
    return ['Akciu sa nepodarilo dokončiť. Skúste si vyžiadať nový e-mail.','The action could not be completed. Request a new email and try again.'];
  }
  async function start(){
    if(!code){$('status').textContent='Chýba bezpečnostný kód.';show('Neplatný odkaz','V odkaze chýba Firebase bezpečnostný kód.','The Firebase security code is missing.',{error:true});return;}
    try{
      if(mode==='verifyEmail'){
        $('status').textContent='Overujeme e-mail…';
        await call('update',{oobCode:code});
        $('status').textContent='✓ E-mail bol úspešne overený.';
        show('E-mail je overený','Účet BlinQ je pripravený. Môžete sa prihlásiť.','Your BlinQ account is ready. You can sign in now.');
        return;
      }
      if(mode==='resetPassword'){
        $('status').textContent='Kontrolujeme odkaz na obnovu hesla…';
        const check=await call('resetPassword',{oobCode:code});
        $('status').textContent=check?.email?`Účet: ${check.email}`:'Odkaz je platný.';
        show('Nastavte nové heslo','Zadajte nové heslo k účtu BlinQ.','Enter a new password for your BlinQ account.',{home:false});
        $('resetForm').classList.remove('hidden');
        $('password').focus();
        return;
      }
      if(mode==='recoverEmail'){
        $('status').textContent='Obnovujeme pôvodnú e-mailovú adresu…';
        await call('update',{oobCode:code});
        $('status').textContent='✓ E-mailová adresa bola obnovená.';
        show('E-mail bol obnovený','Zmena e-mailovej adresy bola vrátená späť.','The email address change has been reverted.');
        return;
      }
      $('status').textContent='Nepodporovaný typ odkazu.';
      show('Neznáma akcia','Tento BlinQ odkaz nemá podporovaný typ akcie.','This BlinQ link contains an unsupported action.',{error:true});
    }catch(err){const [sk,en]=errorText(err?.code||err?.message||'');$('status').textContent='Odkaz sa nepodarilo spracovať.';show('Odkaz sa nedá použiť',sk,en,{error:true});}
  }
  $('resetForm').addEventListener('submit',async e=>{e.preventDefault();const p=$('password').value,p2=$('password2').value;if(p!==p2){$('status').classList.add('error');$('status').textContent='Heslá sa nezhodujú / Passwords do not match.';return;}try{$('status').classList.remove('error');$('status').textContent='Ukladáme nové heslo…';await call('resetPassword',{oobCode:code,newPassword:p});$('resetForm').classList.add('hidden');$('status').textContent='✓ Heslo bolo zmenené.';show('Heslo je zmenené','Môžete sa prihlásiť do BlinQ novým heslom.','You can now sign in to BlinQ with your new password.');}catch(err){const [sk,en]=errorText(err?.code||err?.message||'');$('status').classList.add('error');$('status').textContent=`${sk} / ${en}`;}});
  start();
})();
