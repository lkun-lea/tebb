import {useId} from 'react';
import {ChevronDown,Check} from 'lucide-react';
import type {NoteItem} from './note';
import {UiButton} from './ui-controls';
import {Markdown} from './Markdown';
import {noteExcerpt} from './note-excerpt';

export type SavedNoteRow = NoteItem & {session:string;group:string};
type Props = {
  note:SavedNoteRow; expanded:boolean; added:boolean; busy:boolean; disabled:boolean;
  onToggle:()=>void; onAdd:()=>void; onEdit:()=>void;
  onFile:(action:'open'|'reveal',id:string,name:string,session:string)=>void;
};

export function SavedNoteCard({note,expanded,added,busy,disabled,onToggle,onAdd,onEdit,onFile}:Props) {
  const details=useId();
  return <article className="sn-card" aria-label={note.question}>
    <div className="sn-card-head">
      <button type="button" className="sn-card-read" aria-expanded={expanded} aria-controls={details} onClick={onToggle}>
        <strong>{note.question}<ChevronDown size={14} aria-hidden="true"/></strong>
        {!expanded&&<span className="sn-excerpt">{noteExcerpt(note.answer,note.question)}</span>}
        <small><time>{note.saved.slice(0,10)}</time> · {note.group}</small>
      </button>
      <UiButton className="sn-add" busy={busy} busyLabel="正在加入…" disabled={added||disabled} onClick={onAdd}>
        {added&&<Check size={14} aria-hidden="true"/>}{added?'已加入':'加入会话'}
      </UiButton>
    </div>
    <div id={details} hidden={!expanded}>{expanded&&<>
      <Markdown text={note.answer}/>
      {!!note.cites.length&&<details><summary>来源 · {note.cites.length}</summary>{note.cites.map((c,i)=><blockquote key={i}><strong>{c.doc} · {c.title}</strong><p>{c.text}</p></blockquote>)}</details>}
      {!!note.files.length&&<details><summary>关联文件 · {note.files.length}</summary>{note.files.map(f=><p key={f.name}>{f.name} <UiButton onClick={()=>onFile('open',note.id,f.name,note.session)}>预览</UiButton> <UiButton onClick={()=>onFile('reveal',note.id,f.name,note.session)}>所在文件夹</UiButton></p>)}</details>}
      <footer><UiButton onClick={onEdit}>编辑笔记</UiButton></footer>
    </>}</div>
  </article>;
}
