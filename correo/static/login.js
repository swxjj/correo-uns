'use strict';
const form=document.querySelector('#login-form');
const status=document.querySelector('#login-status');
function preview(){const surname=form.elements.surname.value.trim().toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'');document.querySelector('#address-preview').textContent=(surname||'apellido')+'.'+(form.elements.lu.value||'LU')+'@alu.uns.edu.ar';}
form.elements.surname.addEventListener('input',preview);form.elements.lu.addEventListener('input',preview);
form.addEventListener('submit',async event=>{
  event.preventDefault();const button=document.querySelector('#login-submit');button.disabled=true;status.textContent='Comprobando POP3 y SMTP de forma segura…';
  try{
    const response=await fetch('/api/auth/login',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content},body:JSON.stringify(Object.fromEntries(new FormData(form)))});
    const result=await response.json();if(!response.ok)throw Error(result.detail||'No se pudo completar el ingreso.');
    form.elements.password.value='';window.location.replace('/');
  }catch(error){status.textContent=error.message;form.elements.password.value='';form.elements.password.focus();}finally{button.disabled=false;}
});
