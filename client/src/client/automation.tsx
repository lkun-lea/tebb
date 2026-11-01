import { lazy, Suspense } from "react";
import type { BackendInfo } from "./api";
const WorkflowPane=lazy(()=>import("./workflow-editor").then(module=>({default:module.WorkflowPane})));
export function AutomationPane({info,debug=false}:{info:BackendInfo|null;debug?:boolean;onOpenExecution?:(conversation:string)=>void}){
  return <section className="automation-workspace" data-testid="automation-pane"><Suspense fallback={<p>正在打开工作流设计页…</p>}><WorkflowPane info={info} debug={debug}/></Suspense></section>;
}
