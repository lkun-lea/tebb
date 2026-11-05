// Run in this preview's frame console. It pauses the preview in the wave pose.
// Compare the real shader's gesture on/off at the same time and with the same
// source image, so breathing and head movement do not contaminate the check.
(async () => {
  const root = document.getElementById('tebb-profile-v2-motion');
  if (!root?.motionReviewSnapshot) throw new Error('Select the second-version character preview frame first.');
  const initial = root.motionReviewSnapshot();
  if (!initial.ready || initial.unavailable) throw new Error('The preview renderer is unavailable.');
  if (initial.playing) root.querySelector('[data-play]').click();
  root.querySelector('[data-motion="wave"]').click();
  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  const canvas = root.querySelector('.motion-canvas');
  const gl = canvas.getContext('webgl');
  if (!gl || gl.isContextLost()) throw new Error('WebGL is unavailable.');
  const program = gl.getParameter(gl.CURRENT_PROGRAM);
  const time = gl.getUniformLocation(program, 'u_time');
  const mode = gl.getUniformLocation(program, 'u_mode');
  const count = gl.getBufferParameter(gl.ELEMENT_ARRAY_BUFFER, gl.BUFFER_SIZE) / 2;
  // Rectangles use original middle-portrait coordinates, before canvas fit.
  const regions = {
    shoulder: [25,310,108,450], cuff: [20,470,115,600],
    torso: [180,310,440,750], otherShoulder: [350,300,450,450],
    hand: [110,265,190,390]
  };
  const draw = (seconds, gesture) => {
    gl.uniform1f(time, seconds);
    gl.uniform1f(mode, gesture ? 2 : 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.drawElements(gl.TRIANGLES, count, gl.UNSIGNED_SHORT, 0);
    const data = new Uint8Array(canvas.width*canvas.height*4);
    gl.readPixels(0,0,canvas.width,canvas.height,gl.RGBA,gl.UNSIGNED_BYTE,data);
    return data;
  };
  const phases = [];
  for (const seconds of [0,.5,1,1.5,2,2.5,3,3.5]) {
    const reference = draw(seconds, false), actual = draw(seconds, true);
    const phase = {seconds, regions:{}};
    for (const [name, box] of Object.entries(regions)) {
      const scale = canvas.width/576;
      const x0 = Math.floor((box[0]+40.5)*scale), x1 = Math.ceil((box[2]+40.5)*scale);
      const y0 = Math.floor((box[1]+32)*scale), y1 = Math.ceil((box[3]+32)*scale);
      let changed=0, maxDelta=0;
      for (let y=y0; y<y1; y++) for (let x=x0; x<x1; x++) {
        const index=((canvas.height-1-y)*canvas.width+x)*4;
        if (Math.max(actual[index+3],reference[index+3])<16) continue;
        let delta=0;
        for (let c=0; c<4; c++) delta=Math.max(delta,Math.abs(actual[index+c]-reference[index+c]));
        if (delta>2) changed++;
        maxDelta=Math.max(maxDelta,delta);
      }
      phase.regions[name]={changed,maxDelta};
    }
    phases.push(phase);
  }
  draw(0,true);
  const protectedStable = phases.every(phase => ['shoulder','cuff','torso','otherShoulder'].every(name => phase.regions[name].maxDelta===0));
  const handMoves = phases.some(phase => phase.regions.hand.changed>20);
  return {status:protectedStable&&handMoves?'passed':'failed', protectedStable, handMoves, phases,
    limitation:'Checks these sample regions only; not Live2D, full-transition, frame-rate or visual-quality acceptance.'};
})()
