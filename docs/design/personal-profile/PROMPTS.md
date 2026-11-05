# 角色生成记录

第二版完整人物原画及自然手势已另存 [live2d-v2](live2d-v2/README.md)，包含本轮完整生成与手势修订提示；以下保留初版来源。

2026-11-05，通过 OpenAI 内置 `image_gen` 工具生成；未使用 CLI 或自建图片 API。原始设计为不含黄色光晕的浅色背景静态稿，分层原稿使用真正透明背景。以下保留生成时的主要提示文本与各角色约束，便于后续迭代保持身份；实际采用的原图由 Git 文件固定，不承诺重新生成像素完全一致的图片。

## 三种静态设计

共用提示：

```text
Use case: stylized-concept. Create ONE original cartoon avatar concept for a personal user-profile screen in the tebb desktop app. Polished modern flat 2D editorial cartoon with confident clean charcoal outlines, carefully designed silhouette, large simple color shapes and only very restrained cel shading. Refined and appealing to adults, friendly and expressive. Palette shared with a restrained desktop UI: warm ivory, charcoal, muted warm gray, small desaturated ochre-gold accent. Square composition, full body centered occupying 76% of image height, front-facing with a very slight three-quarter turn, one hand gently raised in a small greeting, the other relaxed. Enough clear space around the whole silhouette, all limbs and feet visible. Uniform flat near-white warm gray background #f8f7f3, no yellow background, no halo, no glow, no ring, no ground shadow, no scene, no border, no lettering or watermark. This is a static character-design concept, no animation frames or interface.
```

漫画分身追加提示：

```text
Subject: an androgynous young-adult HUMAN cartoon alter ego, about 2.5 heads tall, oversized but well-structured head, compact slender body with clear neck, shoulders, arms and legs. Distinctive geometric dark tousled short hair with one subtle outward flick; thin round charcoal glasses, tiny simplified nose, expressive eyebrows and small asymmetrical confident smile. Warm natural light-medium skin tone. Modern simple outfit: a cropped ivory casual jacket open over a muted gold top, straight charcoal trousers, simple ivory sneakers. Readable separate hands with a few minimal finger lines. Stylized contemporary comic drawing, sharp visual hierarchy and elegant silhouette, not a realistic portrait, not a baby, not a toy, not a bean-shaped mascot.
```

几何小机器人追加提示：

```text
Subject: a compact original ROBOT with a distinctive rounded-square head, subtly chamfered upper corner, warm ivory casing and a charcoal inset face display. Two simple expressive pale horizontal capsule eyes and a small curved smile on the display; a tiny off-center muted gold status tab on the head adds identity. Clear short neck, small rounded rectangular torso with one restrained gold chest panel, short flexible limbs with simple rounded joint connections, mitten-like grippers, two clearly separated little feet planted on the ground. Head about 43 percent of total character height, light agile body rather than heavy armor. Warm intelligence, approachable utility, restrained original industrial character design; flat editorial cartoon. No bulky mechanical detail, no antenna forest, no exposed wiring, no lights or glow, no plush or 3D material.
```

原创小兔追加提示：

```text
Subject: an original small upright SHORT-EARED RABBIT cartoon companion, one short upright ear and one gently folded ear for a recognizable asymmetric silhouette. Warm gray fur expressed entirely through flat color shapes, ivory muzzle and tummy patch, charcoal inner-ear marks, tiny dark oval eyes with expressive brow, small rounded triangular nose and a playful understated smile, two fine whisker strokes on each side. A simple cropped muted ochre utility vest provides a small clothing accent; no scarf, no props. Compact but agile silhouette with a clear smaller torso under the head, separated short arms, longish rounded rabbit feet and tiny tail. Head with ears about 48 percent of total character height. Sophisticated contemporary 2D character illustration rather than a plush, fuzzy, doughy or baby-animal look.
```

## 分层原稿

每种角色以对应静态设计为唯一编辑目标，保留造型、配色、服装与描边。要求 4×2 等格、透明背景，顺序为躯干与腿、无眼头部、左上臂、左前臂与手、右上臂、右前臂与手、眼睛、完整站姿参考；关节端点可重叠，所有组件独立留透明边距。机器人和小兔首次请求连接失败后使用同一工具重试，没有改用其他模型或 CLI。

机器人和小兔最终采用的共用编辑提示：

```text
Edit the attached original character into ONE transparent 4-column by 2-row equal-cell puppet-part atlas, aspect ratio 2:1, preserving its exact clean flat cartoon outlines, colors, original design and identity. The eight cells in row-major order must contain: 0 torso+neck+legs+feet, with no head and no arms; 1 whole head with hair/ears/face/mouth retained but NO EYES; 2 viewer-left upper arm, shoulder at top elbow at bottom, vertically hanging; 3 viewer-left lower arm+hand, elbow at top, hand at bottom; 4 viewer-right upper arm, shoulder at top elbow at bottom, vertically hanging; 5 viewer-right lower arm+hand, elbow at top hand at bottom; 6 just the pair of original eyes on transparency, same relative spacing, no face patch; 7 whole assembled neutral character with both arms lowered for reference. Each component centered separately, enlarged to fill roughly 70 percent of its cell with clear transparent margins. Joint endpoints rounded with overlap for seamless assembly. No labels, text, grid lines, halo, glow, yellow background, floor, shadows, or scene. The missing arms/head/eyes must be cleanly removed from torso/head, not leave residual paint.
```

身份约束：漫画分身保留深色头发、圆框眼镜、肤色、象牙色外套、金色内搭和深色裤子；机器人保留浅色圆角头壳、深色屏幕、浅色笑脸与眼睛、头顶和胸前金色面板；小兔保留灰棕色、浅色口鼻/腹部/手脚、不对称耳朵、胡须与工装背心。头部保留嘴、眉、眼镜框或口鼻，只把眼睛分出；躯干保留颈部并完整填补移除的头和手臂区域。
