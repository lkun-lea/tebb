// React renderer tests own state/semantics; real DOM animation is verified in Chromium.
const React=require('react');const tags={};
const motion=new Proxy({},{get:(_,tag)=>tags[tag]||=(React.forwardRef(({children,initial,animate,exit,transition,layout,...props},ref)=>React.createElement(tag,{...props,ref},children)))});
module.exports={motion,useReducedMotion:()=>true,AnimatePresence:({children})=>children};
