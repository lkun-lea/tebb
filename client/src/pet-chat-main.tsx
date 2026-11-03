import { createRoot } from 'react-dom/client';
import 'reend-components/styles.css';
import './client/index.css';
import './client/chat-prototype.css';
import { PetChat } from './client/pet-chat';
import {useEffect} from 'react';
import {AccountBootstrap} from './client/account-bootstrap';
import {accountStorage,accountStorageKey} from './client/account-storage';

function AccountPetChat(){
  useEffect(()=>{
    const apply=(value:string|null)=>{document.documentElement.classList.toggle('light',value==='light');document.documentElement.classList.toggle('dark',value!=='light');};
    try{apply(accountStorage().getItem('tebb.theme'));}catch{/* use default theme */}
    const changed=(event:StorageEvent)=>{if(event.key===accountStorageKey('tebb.theme'))apply(event.newValue);};
    window.addEventListener('storage',changed);return()=>window.removeEventListener('storage',changed);
  },[]);
  return <PetChat/>;
}
createRoot(document.getElementById('root')!).render(<AccountBootstrap><AccountPetChat/></AccountBootstrap>);
