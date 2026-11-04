import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { copyFileSync, mkdirSync, readFileSync } from "node:fs";

// 两页：index.html 宠物窗（vanilla），client.html 主客户端（React）
export default defineConfig({
  // 发布时不扫描 public，防止把开发机的形象、Core 等私有素材嵌入 exe。
  publicDir: process.env.DESK_RELEASE === "1" ? false : "public",
  clearScreen: false,
  plugins: [react(), {
    name: "release-startup-script",
    writeBundle() {
      if (process.env.DESK_RELEASE === "1") {
        copyFileSync(resolve(__dirname, "public/startup.js"), resolve(__dirname, "dist/startup.js"));
        const assets = JSON.parse(readFileSync(resolve(__dirname, "public/profile-avatars/manifest.json"), "utf8")) as { character: string; part: string }[];
        for (const { character, part } of assets) {
          if (!["comic", "robot", "rabbit"].includes(character) || !["body", "head", "upperL", "lowerL", "upperR", "lowerR", "eyes", "reference"].includes(part)) throw Error("Invalid profile avatar asset manifest");
          const destination = resolve(__dirname, "dist/profile-avatars", character);
          mkdirSync(destination, { recursive: true });
          copyFileSync(resolve(__dirname, "public/profile-avatars", character, part + ".png"), resolve(destination, part + ".png"));
        }
        copyFileSync(resolve(__dirname, "public/profile-avatars/manifest.json"), resolve(__dirname, "dist/profile-avatars/manifest.json"));
      }
    },
  }],
  server: {
    port: 5180,
    strictPort: true,
    // 调试页直接读技能原文，避免再抄一份对照表。
    fs: {
      allow: [resolve(__dirname, "..")],
    },
  },
  build: {
    target: "esnext",
    outDir: "dist",
    rollupOptions: {
      input: {
        pet: resolve(__dirname, "index.html"),
        client: resolve(__dirname, "client.html"),
        petChat: resolve(__dirname, "pet-chat.html"),
      },
    },
  },
});
