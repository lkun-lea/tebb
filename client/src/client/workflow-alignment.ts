export type AlignableNode={id:string;position:{x:number;y:number};selected?:boolean;measured?:{width?:number;height?:number};width?:number;height?:number};
export type AlignmentGuide={axis:'x'|'y';at:number;from:number;to:number};
const size=(node:AlignableNode)=>({width:node.measured?.width||node.width||185,height:node.measured?.height||node.height||72});
export function alignSelection<T extends AlignableNode>(nodes:T[],direction:'horizontal'|'vertical'):T[]{
  const selected=nodes.filter(n=>n.selected);if(selected.length<2)return nodes;
  const axis=direction==='horizontal'?'y':'x',dimension=direction==='horizontal'?'height':'width';
  const start=Math.min(...selected.map(n=>n.position[axis])),end=Math.max(...selected.map(n=>n.position[axis]+size(n)[dimension]));
  return nodes.map(node=>node.selected?{...node,position:{...node.position,[axis]:(start+end-size(node)[dimension])/2}}:node);
}
export function snapAlignment(moving:AlignableNode,nodes:AlignableNode[],zoom=1){
  const threshold=8/Math.max(.05,zoom),movingSize=size(moving),position={...moving.position},guides:AlignmentGuide[]=[];
  for(const axis of ['x','y'] as const){
    const dimension=axis==='x'?'width':'height',other=axis==='x'?'y':'x',otherDimension=axis==='x'?'height':'width';
    let best:{distance:number;offset:number;anchor:number;node:AlignableNode}|undefined;
    for(const node of nodes){
      if(node.id===moving.id||node.selected)continue;
      for(const local of [0,movingSize[dimension]/2,movingSize[dimension]])for(const remote of [0,size(node)[dimension]/2,size(node)[dimension]]){
        const anchor=node.position[axis]+remote,offset=anchor-moving.position[axis]-local,distance=Math.abs(offset);
        if(distance<=threshold&&(!best||distance<best.distance))best={distance,offset,anchor,node};
      }
    }
    if(best){position[axis]+=best.offset;guides.push({axis,at:best.anchor,from:Math.min(moving.position[other],best.node.position[other])-24,to:Math.max(moving.position[other]+movingSize[otherDimension],best.node.position[other]+size(best.node)[otherDimension])+24});}
  }
  return {position,guides};
}
